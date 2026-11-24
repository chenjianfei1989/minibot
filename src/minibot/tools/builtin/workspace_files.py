"""仅使用标准库实现的文件操作。受限助手会在 Docker 内运行这段源码。"""

from contextlib import ExitStack, suppress
import codecs
import json
import os
import re
import stat
import sys
from uuid import uuid4


_LINE_BREAK = re.compile(r"\r\n|[\r\n\v\f\x1c-\x1e\x85\u2028\u2029]")
MAX_MUTATION_BYTES = 16 * 1024 * 1024
MAX_LIST_ENTRIES = 1000
OUTPUT_LIMIT_EXIT = 42


class FileOutputLimit(ValueError):
    """完整读取文件会超出可用的输出预算。"""


def bounded_file_text(file, limit: int | None, max_bytes: int) -> str:
    """在字节预算内读取并解码文本，按需限制返回行数。"""
    data = file.read(max_bytes + 1)
    overflow = len(data) > max_bytes
    decoder = codecs.getincrementaldecoder("utf-8")()
    text = decoder.decode(data, final=not overflow)
    if limit and not isinstance(limit, int):
        raise ValueError("Limit must be an integer.")
    if limit and limit > 0:
        for line, match in enumerate(_LINE_BREAK.finditer(text), start=1):
            if line == limit:
                text = text[:match.end()]
                overflow = len(text.encode("utf-8")) > max_bytes
                break
    if overflow:
        raise FileOutputLimit("File output exceeded the capture limit.")
    if limit and limit < 0:
        text = "".join(text.splitlines(keepends=True)[:limit])
    return text


def bounded_listing(entries):
    """有界地读取目录的直接条目。"""
    names = []
    for entry in entries:
        if len(names) >= MAX_LIST_ENTRIES:
            raise ValueError(f"Directory exceeds the {MAX_LIST_ENTRIES}-entry listing limit.")
        names.append(entry.name)
    return sorted(names)


def restricted_parts(path: str) -> tuple[str, ...]:
    """校验受限工作区相对路径并返回路径组件。"""
    parts = path.split("/")
    if not path or path.startswith("/") or "\\" in path or "\0" in path or ".." in parts:
        raise ValueError(f"Path must be workspace-relative without parent traversal: {path!r}")
    return tuple(part for part in parts if part not in ("", "."))


def _walk_directory(stack, parts, create):
    """逐级打开目录，从给定目录描述符定位目标父目录。"""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    current = os.open("/workspace", flags)
    stack.callback(os.close, current)
    for part in parts:
        if create:
            with suppress(FileExistsError):
                os.mkdir(part, dir_fd=current)
        current = os.open(part, flags, dir_fd=current)
        stack.callback(os.close, current)
    return current


def _regular_file(parent, name):
    """检查指定目录项是否为可以安全操作的普通文件。"""
    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("File must be a regular file with one hard link.")
    return info


def _open_file(parent, name, expected):
    """打开目录项并核验文件类型与状态。"""
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY, dir_fd=parent)
    opened = os.fstat(fd)
    if not os.path.samestat(opened, expected) or opened.st_nlink != 1:
        os.close(fd)
        raise ValueError("File changed while opening.")
    return os.fdopen(fd, "rb")


def _file_version(info):
    """从文件状态提取用于并发检查的版本信息。"""
    if info is None:
        return None
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _replace_file(parent, name, content, expected):
    """把 UTF-8 内容写入暂存文件，核验目标状态后原子替换。"""
    data = content.encode("utf-8")
    if len(data) > MAX_MUTATION_BYTES:
        raise ValueError("File content exceeds the 16 MiB mutation limit.")
    temp_name = f".minibot-write-{uuid4().hex}"
    fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666, dir_fd=parent)
    try:
        with os.fdopen(fd, "wb") as file:
            if expected is not None:
                os.fchmod(file.fileno(), stat.S_IMODE(expected.st_mode))
            file.write(data)
        try:
            current = _regular_file(parent, name)
        except FileNotFoundError:
            current = None
        if _file_version(current) != _file_version(expected):
            raise ValueError("File changed during the operation.")
        os.replace(temp_name, name, src_dir_fd=parent, dst_dir_fd=parent)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temp_name, dir_fd=parent)


def _operation(request):
    """按请求的操作类型分发受限工作区文件操作。"""
    operation = request["operation"]
    parts = restricted_parts(request["path"])
    with ExitStack() as stack:
        if operation == "list":
            fd = _walk_directory(stack, parts, False)
            with os.scandir(fd) as entries:
                return json.dumps(bounded_listing(entries), ensure_ascii=True)
        if not parts:
            raise ValueError("Path must name a file.")
        parent = _walk_directory(stack, parts[:-1], operation == "write")
        name = parts[-1]
        try:
            info = _regular_file(parent, name)
        except FileNotFoundError:
            if operation != "write":
                raise
            info = None
        if operation == "read":
            with _open_file(parent, name, info) as file:
                return bounded_file_text(file, request["limit"], request["max_bytes"])
        if operation == "write":
            _replace_file(parent, name, request["content"], info)
            return ""
        if operation == "edit":
            with _open_file(parent, name, info) as file:
                data = file.read(MAX_MUTATION_BYTES + 1)
            if len(data) > MAX_MUTATION_BYTES:
                raise ValueError("File content exceeds the 16 MiB mutation limit.")
            text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            old_text = request["old_text"]
            if old_text not in text:
                return "false"
            _replace_file(parent, name, text.replace(old_text, request["new_text"], 1), info)
            return "true"
        raise ValueError("Unsupported file operation.")


def _main():
    """读取文件操作请求并输出结果或诊断。"""
    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        sys.stdout.buffer.write(_operation(request).encode("utf-8"))
    except FileOutputLimit as exc:
        sys.stderr.write(f"{exc}\n")
        return OUTPUT_LIMIT_EXIT
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())
