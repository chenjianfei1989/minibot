"""使用 JSONL 持久化会话状态。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .messages import normalize_session_message

PREVIEW_MAX_LEN = 60


@dataclass(frozen=True)
class SessionMeta:
    """已持久化会话的元数据。"""

    session_id: str
    path: Path
    created_at: datetime
    modified_at: datetime
    message_count: int
    preview: str  # 截断后的首条用户消息。


class SessionStore:
    """读取和写入会话历史的底层 JSONL 存储。

    存储布局为 ``<sessions_dir>/yyyy/mm/dd/<session_id>.jsonl``。
    """

    def __init__(self, sessions_dir: Path) -> None:
        """记录会话目录并在需要时创建目录。"""
        self._root = sessions_dir.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _date_subdir(dt: datetime) -> str:
        """将日期格式化成会话文件使用的年、月、日子目录。"""
        return f"{dt:%Y/%m/%d}"

    def _resolve_path(self, session_id: str, date: datetime) -> Path:
        """根据会话 ID 和日期计算 JSONL 文件路径。"""
        return self._root / self._date_subdir(date) / f"{session_id}.jsonl"

    def _find_path(self, session_id: str) -> Path | None:
        """扫描日期子目录，查找已存在的会话文件。"""
        for path in self._root.rglob(f"{session_id}.jsonl"):
            return path
        return None

    def runtime_state_path(self, session_id: str) -> Path | None:
        """返回已有会话文件对应的运行时伴随文件路径。"""
        path = self._find_path(session_id)
        if path is None:
            return None
        return path.with_suffix(".runtime.json")

    def create(self, session_id: str, date: datetime | None = None) -> Path:
        """创建空 JSONL 文件并返回其路径。"""
        dt = date or datetime.now()
        path = self._resolve_path(session_id, dt)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return path

    def append(self, session_id: str, message: dict) -> None:
        """向会话 JSONL 文件追加一条消息。"""
        path = self._find_path(session_id)
        if path is None:
            path = self.create(session_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    def overwrite(self, session_id: str, messages: list[dict]) -> None:
        """使用提供的消息重写会话 JSONL 文件。"""
        path = self._find_path(session_id)
        if path is None:
            path = self.create(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for message in messages:
                f.write(json.dumps(message, ensure_ascii=False) + "\n")

    def project_durable_messages(self, session_id: str, messages: list[dict]) -> None:
        """运行持有会话时，以幂等方式写入日志快照。"""
        path = self._find_path(session_id)
        if path is None:
            path = self.create(session_id)
        previous = self._read_jsonl(path)
        positions = {
            message["message_id"]: index for index, message in enumerate(previous) if message.get("message_id")
        }
        for message in messages:
            message_id = message.get("message_id")
            if not message_id:
                continue
            if message_id not in positions:
                positions[message_id] = len(previous)
                previous.append(message)
            elif message.get("interaction_type") == "askuserquestion":
                index = positions[message_id]
                previous[index] = {**previous[index], **message}
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as tmp:
            temp_path = Path(tmp.name)
            try:
                for message in previous:
                    tmp.write(json.dumps(message, ensure_ascii=False) + "\n")
                tmp.flush()
                os.fsync(tmp.fileno())
            except BaseException:
                tmp.close()
                temp_path.unlink(missing_ok=True)
                raise
        try:
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)

    def update_message(
        self,
        session_id: str,
        message_id: str,
        updater: Callable[[dict[str, Any]], dict[str, Any] | None],
    ) -> dict[str, Any] | None:
        """更新已持久化消息中第一条 message_id 匹配的消息。"""
        path = self._find_path(session_id)
        if path is None:
            return None

        messages = self._read_jsonl(path)
        for index, message in enumerate(messages):
            if message.get("message_id") != message_id:
                continue

            current = dict(message)
            updated = updater(current)
            messages[index] = dict(updated) if updated is not None else current
            self.overwrite(session_id, messages)
            return messages[index]

        return None

    def save_runtime_state(self, session_id: str, payload: dict[str, Any]) -> None:
        """将运行时伴随状态保存为小型 JSON 文件。"""
        path = self.runtime_state_path(session_id)
        if path is None:
            session_path = self.create(session_id)
            path = session_path.with_suffix(".runtime.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, payload)

    def load_runtime_state(self, session_id: str) -> dict[str, Any] | None:
        """如果运行时伴随状态存在，就加载它。"""
        path = self.runtime_state_path(session_id)
        if path is None or not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def delete_runtime_state(self, session_id: str, *, expected: dict[str, Any] | None = None) -> bool:
        """伴随文件存在时删除它。若传入 expected，还须与该值匹配。"""
        path = self.runtime_state_path(session_id)
        if path is None or not path.exists():
            return False
        if expected is not None and self.load_runtime_state(session_id) != expected:
            return False
        path.unlink()
        return True

    def load(self, session_id: str) -> list[dict]:
        """从最后一个压缩点开始，从 JSONL 加载对话历史。"""
        path = self._find_path(session_id)
        if path is None:
            return []
        
        messages = self._read_jsonl(path)
        
        # 若有压缩消息，找出最后一条。
        compaction_index = -1
        for i, msg in enumerate(messages):
            if msg.get("is_compaction"):
                compaction_index = i
                
        if compaction_index >= 0:
            return [normalize_session_message(message) for message in messages[compaction_index:]]
            
        return [normalize_session_message(message) for message in messages]

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        """读取 UTF-8 JSONL 文件并逐行解析会话记录。"""
        messages: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            messages.append(json.loads(line))
        return messages

    def delete(self, session_id: str) -> bool:
        """删除会话文件，找到并成功删除时返回 True。"""
        path = self._find_path(session_id)
        if path is None:
            return False
        runtime_path = path.with_suffix(".runtime.json")
        path.unlink()
        if runtime_path.exists():
            runtime_path.unlink()
        # 清理空的上级日期目录。
        for parent in [path.parent, path.parent.parent, path.parent.parent.parent]:
            if parent == self._root:
                break
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        return True

    def list_sessions(self) -> list[SessionMeta]:
        """列出所有会话，按修改时间降序排列。"""
        results: list[SessionMeta] = []
        for path in self._root.rglob("*.jsonl"):
            meta = self._build_meta(path)
            if meta is not None:
                results.append(meta)
        results.sort(key=lambda m: m.modified_at, reverse=True)
        return results

    def _build_meta(self, path: Path) -> SessionMeta | None:
        """从会话文件提取消息数量、预览内容和文件时间等元数据。"""
        session_id = path.stem
        try:
            stat = path.stat()
        except OSError:
            return None

        # macOS 提供 st_birthtime，Linux 通常没有此字段，此时使用 st_ctime。
        created_ts = getattr(stat, "st_birthtime", None)
        if created_ts is None:
            created_ts = stat.st_ctime
        created_at = datetime.fromtimestamp(created_ts)
        modified_at = datetime.fromtimestamp(stat.st_mtime)

        messages = self._read_jsonl(path)
        preview = ""
        for msg in messages:
            if msg.get("role") == "user":
                raw = msg.get("content", "")
                preview = (raw[:PREVIEW_MAX_LEN - 3] + "...") if len(raw) > PREVIEW_MAX_LEN else raw
                break

        return SessionMeta(
            session_id=session_id,
            path=path,
            created_at=created_at,
            modified_at=modified_at,
            message_count=len(messages),
            preview=preview,
        )

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        """在目标目录内以原子操作写入 JSON 文件。"""
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            json.dump(payload, tmp, ensure_ascii=False)
            tmp.flush()
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
