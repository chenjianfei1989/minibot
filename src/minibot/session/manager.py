"""会话生命周期管理。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

from .store import SessionStore, SessionMeta

SESSION_ID_LEN = 8


class SessionManager:
    """提供会话创建、加载、保存、列出和删除操作。"""

    def __init__(self, sessions_dir: Path) -> None:
        """绑定会话存储目录，初始化底层 JSONL 存储。"""
        self.sessions_dir = sessions_dir.resolve()
        self.store = SessionStore(self.sessions_dir)

    def create(self) -> str:
        """创建新会话并返回其 ID。"""
        session_id = str(uuid.uuid4())[:SESSION_ID_LEN]
        self.store.create(session_id)
        return session_id

    def load(self, session_id: str) -> list[dict]:
        """加载会话的对话历史。"""
        return self.store.load(session_id)

    def append_message(self, session_id: str, message: dict) -> None:
        """将一条消息持久化到会话。"""
        self.store.append(session_id, message)

    def overwrite(self, session_id: str, messages: list[dict]) -> None:
        """重写会话的完整对话历史。"""
        self.store.overwrite(session_id, messages)

    def runtime_state_path(self, session_id: str) -> Path | None:
        """返回已存在的会话运行时伴随文件路径。"""
        return self.store.runtime_state_path(session_id)

    def save_runtime_state(self, session_id: str, payload: dict[str, Any]) -> None:
        """持久化会话运行时状态。"""
        self.store.save_runtime_state(session_id, payload)

    def load_runtime_state(self, session_id: str) -> dict[str, Any] | None:
        """加载会话运行时状态。"""
        return self.store.load_runtime_state(session_id)

    def delete_runtime_state(self, session_id: str, *, expected: dict[str, Any] | None = None) -> bool:
        """伴随文件存在时删除它。若传入 expected，还须与该值匹配。"""
        return self.store.delete_runtime_state(session_id, expected=expected)

    def update_message(
        self,
        session_id: str,
        message_id: str,
        updater: Callable[[dict[str, Any]], dict[str, Any] | None],
    ) -> dict[str, Any] | None:
        """就地更新已持久化的消息。"""
        return self.store.update_message(session_id, message_id, updater)

    def list_all(self) -> list[SessionMeta]:
        """列出所有会话，按修改时间降序排列。"""
        return self.store.list_sessions()

    def delete(self, session_id: str) -> bool:
        """删除会话，找到时返回 True。"""
        return self.store.delete(session_id)

    def get_latest(self) -> str | None:
        """返回最近修改的会话的 session_id。"""
        sessions = self.store.list_sessions()
        if not sessions:
            return None
        return sessions[0].session_id

    def exists(self, session_id: str) -> bool:
        """检查会话文件是否存在。"""
        return self.store._find_path(session_id) is not None
