"""按会话保存完整的文本工具结果。"""

from __future__ import annotations

import base64
from collections.abc import Callable
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from heapq import nlargest
import json
import os
from pathlib import Path
import re
import stat
from tempfile import NamedTemporaryFile
from typing import BinaryIO, Literal
from uuid import uuid4

from ..config.schema import MAX_ARTIFACT_BYTES


_ID = re.compile(r"[A-Za-z0-9_-]{21}[AQgw]")
_HEADER_LIMIT = 4096
_CATALOG_SIZE = 8
MAX_READ_CHARS = 4096
MAX_QUERY_CHARS = 256


class ArtifactError(RuntimeError):
    """产物操作失败，错误信息不暴露存储路径。"""


class InvalidArtifactRequest(ArtifactError):
    """检索请求包含无效参数。"""


@dataclass(frozen=True)
class ArtifactMetadata:
    artifact_id: str
    run_id: str
    tool_name: str
    created_at: str
    size_bytes: int
    content_type: str
    location: str
    workspace_id: str | None = None


@dataclass(frozen=True)
class ArtifactMatch:
    offset: int
    snippet_start: int
    snippet: str


def _private(info: os.stat_result) -> bool:
    """检查文件或目录在当前平台上的权限是否符合私有存储要求。"""
    return os.name != "posix" or (info.st_uid == os.getuid() and not info.st_mode & 0o077)


class ArtifactStore:
    """在应用管理的目录内，为每个 ID 发布一份大小受限的记录。"""

    def __init__(
        self, app_home: Path, workdir: Path, sessions_dir: Path, session_id: str, max_bytes: int,
        *, workspace_id: str | None = None,
    ) -> None:
        """根据应用主目录建立产物存储，并记录单个产物的大小上限。"""
        self.root = app_home.resolve() / "artifacts"
        identity = b"\0".join([
            os.fsencode(workdir.resolve()), os.fsencode(sessions_dir.resolve()), session_id.encode("utf-8"),
        ])
        self.workspace_id = workspace_id
        if workspace_id is not None:
            identity += b"\0" + workspace_id.encode("ascii")
        self.directory = self.root / sha256(identity).hexdigest()
        self.max_bytes = max_bytes

    def _check_directories(self, *, create: bool = False) -> None:
        """检查产物根目录和会话目录是否满足存储要求。"""
        for path in (self.root, self.directory):
            if create:
                path.mkdir(mode=0o700, parents=path == self.root, exist_ok=True)
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or not _private(info) or path.resolve() != path:
                raise ArtifactError("Artifact storage is not private.")

    def _keyed_identifier(self, content: bytes, run_id: str, tool_name: str, key: str) -> bytes:
        """由键和内容计算可重复使用的产物标识。"""
        scope = json.dumps([self.directory.name, run_id, tool_name, key], ensure_ascii=True)
        return sha256(scope.encode("ascii") + b"\0" + content).digest()[:16]

    def save(
        self, text: str, run_id: str, tool_name: str, *, key: str | None = None,
    ) -> ArtifactMetadata:
        """保存文本。提供键和相同内容时，可复用对应的不可变记录。"""
        if len(text) > self.max_bytes:
            raise ArtifactError(f"Output exceeds the {self.max_bytes}-byte artifact limit.")
        try:
            content = text.encode("utf-8")
        except UnicodeError as exc:
            raise ArtifactError("Output is not valid UTF-8 text.") from exc
        if len(content) > self.max_bytes:
            raise ArtifactError(f"Output exceeds the {self.max_bytes}-byte artifact limit.")

        identifier = uuid4().bytes if key is None else self._keyed_identifier(content, run_id, tool_name, key)
        artifact_id = base64.urlsafe_b64encode(identifier).decode("ascii").rstrip("=")
        metadata = ArtifactMetadata(
            artifact_id, run_id, tool_name, datetime.now(timezone.utc).isoformat(),
            len(content), "text/plain; charset=utf-8", f"{artifact_id}.artifact", self.workspace_id,
        )
        fields = asdict(metadata)
        if metadata.workspace_id is None:
            del fields["workspace_id"]
        header = json.dumps(fields, ensure_ascii=True).encode("ascii") + b"\n"
        if len(header) > _HEADER_LIMIT:
            raise ArtifactError("Artifact metadata exceeds its storage limit.")
        temporary = None
        try:
            self._check_directories(create=True)
            with NamedTemporaryFile("wb", prefix=".pending-", dir=self.directory, delete=False) as file:
                temporary = Path(file.name)
                file.write(header)
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            destination = self.directory / metadata.location
            if key is None:
                os.replace(temporary, destination)
            else:
                try:
                    os.link(temporary, destination)
                except FileExistsError:
                    existing, payload = self.read_all(artifact_id)
                    if existing.run_id != run_id or existing.tool_name != tool_name or payload != text:
                        raise ArtifactError("Immutable artifact record does not match its contents.")
                    return existing
        except OSError as exc:
            raise ArtifactError("Artifact storage unavailable.") from exc
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)
        return metadata

    @staticmethod
    def _open_record(path: str, flags: int) -> int:
        """打开指定 ID 的产物记录并检查其文件状态。"""
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or not _private(info):
            raise ArtifactError("Artifact unavailable.")
        descriptor = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or not _private(opened) or not os.path.samestat(info, opened):
                raise ArtifactError("Artifact unavailable.")
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    @staticmethod
    def _metadata(file: BinaryIO, artifact_id: str) -> ArtifactMetadata:
        """从产物记录提取大小、作用域及来源等元数据。"""
        header = file.readline(_HEADER_LIMIT + 1)
        if len(header) > _HEADER_LIMIT or not header.endswith(b"\n"):
            raise ArtifactError("Invalid artifact record.")
        metadata = ArtifactMetadata(**json.loads(header))
        if (
            metadata.artifact_id != artifact_id or metadata.location != f"{artifact_id}.artifact"
            or type(metadata.size_bytes) is not int or metadata.size_bytes < 0
            or not isinstance(metadata.tool_name, str)
        ):
            raise ArtifactError("Invalid artifact record.")
        return metadata

    def _load(self, artifact_id: str, *, include_content: bool) -> tuple[ArtifactMetadata, str]:
        """读取并解析指定的产物记录。"""
        if not isinstance(artifact_id, str) or _ID.fullmatch(artifact_id) is None:
            raise InvalidArtifactRequest("Invalid artifact ID.")
        try:
            self._check_directories()
            path = self.directory / f"{artifact_id}.artifact"
            with open(path, "rb", opener=self._open_record) as file:
                metadata = self._metadata(file, artifact_id)
                if metadata.workspace_id != self.workspace_id:
                    raise ArtifactError("Artifact unavailable in this workspace.")
                if not include_content:
                    return metadata, ""
                if metadata.size_bytes > self.max_bytes:
                    raise ArtifactError("Artifact exceeds the configured size limit.")
                data = file.read(metadata.size_bytes + 1)
                if len(data) != metadata.size_bytes:
                    raise ArtifactError("Invalid artifact record.")
                return metadata, data.decode("utf-8")
        except (FileNotFoundError, PermissionError) as exc:
            raise ArtifactError("Artifact unavailable in this session.") from exc
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            raise ArtifactError("Invalid or unavailable artifact record.") from exc

    def read(self, artifact_id: str, offset: int, limit: int) -> tuple[ArtifactMetadata, str]:
        """读取产物正文的指定字符范围，返回切片和元数据。"""
        if type(offset) is not int or offset < 0:
            raise InvalidArtifactRequest("Offset must be a nonnegative integer.")
        if type(limit) is not int or not 1 <= limit <= MAX_READ_CHARS:
            raise InvalidArtifactRequest(f"Limit must be between 1 and {MAX_READ_CHARS}.")
        metadata, text = self._load(artifact_id, include_content=True)
        if offset > len(text):
            raise InvalidArtifactRequest("Offset is past the end of the artifact.")
        return metadata, text[offset:offset + limit]

    def read_all(self, artifact_id: str, *, key: str | None = None) -> tuple[ArtifactMetadata, str]:
        """读取大小受限的记录，提供键时同时进行校验。"""
        metadata, content = self._load(artifact_id, include_content=True)
        if key is not None:
            identifier = self._keyed_identifier(content.encode("utf-8"), metadata.run_id, metadata.tool_name, key)
            if base64.urlsafe_b64encode(identifier).decode("ascii").rstrip("=") != artifact_id:
                raise ArtifactError("Immutable artifact record does not match its key and contents.")
        return metadata, content

    def search(self, artifact_id: str, query: str) -> tuple[ArtifactMetadata, list[ArtifactMatch]]:
        """按字面文本查询产物，返回受限的匹配片段和元数据。"""
        if not isinstance(query, str) or not 1 <= len(query) <= MAX_QUERY_CHARS:
            raise InvalidArtifactRequest(f"Query must contain 1 to {MAX_QUERY_CHARS} characters.")
        metadata, text = self._load(artifact_id, include_content=True)
        matches = []
        start = 0
        while len(matches) < 20:
            offset = text.find(query, start)
            if offset == -1:
                break
            snippet_start = max(0, offset - 32)
            snippet = text[snippet_start:offset + len(query) + 32]
            matches.append(ArtifactMatch(offset, snippet_start, snippet))
            start = offset + 1
        return metadata, matches

    def recent(self) -> list[ArtifactMetadata]:
        """查找一定数量的近期发布记录，无需加载正文。"""
        try:
            self._check_directories()
            with os.scandir(self.directory) as entries:
                records = (
                    (item.stat(follow_symlinks=False).st_mtime_ns, item.name.removesuffix(".artifact"))
                    for item in entries if item.name.endswith(".artifact") and item.is_file(follow_symlinks=False)
                )
                latest = nlargest(_CATALOG_SIZE, records)
        except (OSError, ArtifactError):
            return []
        result = []
        for _, artifact_id in latest:
            try:
                metadata, _ = self._load(artifact_id, include_content=False)
            except ArtifactError:
                continue
            result.append(metadata)
        return result


ArtifactEvent = Literal["artifact_created", "artifact_read", "artifact_search"]
ArtifactObserver = Callable[[ArtifactEvent, ArtifactMetadata], None]


@dataclass(frozen=True)
class ArtifactRun:
    store: ArtifactStore
    run_id: str
    threshold_chars: int
    output_chars: int
    observe: ArtifactObserver | None
    catalog: list[ArtifactMetadata] = field(default_factory=list)

    def record(self, event: ArtifactEvent, metadata: ArtifactMetadata) -> None:
        """创建事件到来时更新近期产物目录，并将产物事件通知追踪回调。"""
        if event == "artifact_created":
            self.catalog.insert(0, metadata)
            del self.catalog[_CATALOG_SIZE:]
        if self.observe is not None:
            self.observe(event, metadata)

    @property
    def capture_bytes(self) -> int:
        """计算捕获上限，兼顾产物字节限制和内联字符阈值。"""
        max_inline_bytes = min(self.threshold_chars * 4, MAX_ARTIFACT_BYTES)
        return max(self.store.max_bytes, max_inline_bytes)

    def failure(self, detail: str) -> str:
        """构造产物保存失败时使用的工具结果。"""
        return f"Tool ran. Output not saved. {detail}"[:self.output_chars]

    def context(self) -> str:
        """生成可供模型使用的近期产物说明。"""
        if not self.catalog:
            return ""
        names = [re.sub(r"[^A-Za-z0-9_-]", "?", item.tool_name[:64]) for item in self.catalog]
        listing = "\n".join(
            f"{item.artifact_id} ({name}, {item.size_bytes} bytes)"
            for item, name in zip(self.catalog, names, strict=True)
        )
        return (
            "\n\nRecent session artifacts (outputs stored separately). "
            "Use read_artifact or search_artifact when permitted.\n" + listing
        )


current_artifacts: ContextVar[ArtifactRun | None] = ContextVar("context_artifacts", default=None)
