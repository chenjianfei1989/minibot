#!/usr/bin/env python3
"""将文件访问限制在工作目录内。"""

import json
import os
import re
import shlex
from pathlib import Path


def extract_paths_from_bash(command: str) -> list[str]:
    """从 Bash 命令中提取可能的文件路径。"""
    paths = []

    # 尝试对命令进行分词。
    try:
        tokens = shlex.split(command)
    except ValueError:
        # 如果 shlex 解析失败，回退到简单的字符串拆分。
        tokens = command.split()

    for token in tokens:
        # 跳过命令行选项。
        if token.startswith("-"):
            continue
        # 处理绝对路径。
        if token.startswith("/"):
            paths.append(token)
        # 处理包含上级目录跳转的相对路径。
        elif ".." in token:
            paths.append(token)
        # 展开用户主目录。
        elif token.startswith("~"):
            paths.append(os.path.expanduser(token))

    # 同时检查重定向，例如 > /path、>> /path 和 < /path。
    redirect_pattern = r'[<>]{1,2}\s*([/~][^\s;|&]*|[^\s;|&]*\.\.+[^\s;|&]*)'
    for match in re.finditer(redirect_pattern, command):
        path = match.group(1).strip()
        if path.startswith("~"):
            path = os.path.expanduser(path)
        paths.append(path)

    return paths


def is_path_within_workdir(file_path: str, workdir: str) -> tuple[bool, str]:
    """检查指定路径是否位于工作目录内。"""
    workdir_path = Path(workdir).resolve()

    # 处理相对路径。
    if not Path(file_path).is_absolute():
        target_path = (workdir_path / file_path).resolve()
    else:
        target_path = Path(file_path).resolve()

    try:
        target_path.relative_to(workdir_path)
        return True, ""
    except ValueError:
        return False, str(target_path)


def main():
    tool_name = os.environ.get("HOOK_TOOL_NAME", "")
    tool_args_raw = os.environ.get("HOOK_TOOL_ARGS", "{}")
    workdir = os.environ.get("HOOK_WORKDIR", "")

    # 列出需要检查文件访问的工具。
    file_tools = {"read_file", "write_file", "edit_file", "bash"}
    if tool_name not in file_tools:
        print(json.dumps({"success": True}))
        return

    try:
        args = json.loads(tool_args_raw)
    except json.JSONDecodeError:
        print(json.dumps({"success": True}))
        return

    paths_to_check = []

    # 确定需要检查的文件路径。
    if tool_name in ("read_file", "write_file", "edit_file"):
        file_path = args.get("path") or args.get("file_path", "")
        if file_path:
            paths_to_check.append(file_path)
    elif tool_name == "bash":
        command = args.get("command", "")
        if command:
            paths_to_check = extract_paths_from_bash(command)

    if not paths_to_check:
        print(json.dumps({"success": True}))
        return

    # 检查所有路径。
    for path in paths_to_check:
        is_valid, resolved_path = is_path_within_workdir(path, workdir)
        if not is_valid:
            print(json.dumps({
                "success": True,
                "blocked": True,
                "block_reason": f"Access to files outside working directory is not allowed: {path} (resolves to {resolved_path})",
            }))
            return

    print(json.dumps({"success": True}))


if __name__ == "__main__":
    main()
