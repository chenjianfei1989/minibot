"""记录活跃流的所有者，防止同一会话同时启动多个生成任务。"""

import asyncio
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Iterator

from ..session.manager import SessionManager


_owners: dict[tuple[Path, str], tuple[str, asyncio.Task]] = {}
_lock = Lock()


def _live_owner(key: tuple[Path, str]) -> tuple[str, asyncio.Task] | None:
    """查找指定会话的活跃流所有者，并清理已完成或事件循环已关闭的记录。"""
    owner = _owners.get(key)
    if owner and (owner[1].done() or owner[1].get_loop().is_closed()):
        del _owners[key]
        return None
    return owner


def is_active_stream(manager: SessionManager, session_id: str, run_id: object) -> bool:
    """判断指定运行是否仍持有该会话的流所有权。"""
    with _lock:
        owner = _live_owner((manager.sessions_dir, session_id))
        return owner is not None and owner[0] == run_id


@contextmanager
def own_stream(manager: SessionManager | None, session_id: str, run_id: str) -> Iterator[None]:
    """在上下文内占用会话的流所有权，防止同一会话同时启动多个生产者。"""
    if manager is None:
        yield
        return

    key = (manager.sessions_dir, session_id)
    task = asyncio.current_task()
    assert task is not None
    with _lock:
        if _live_owner(key) is not None:
            raise RuntimeError("A stream is already running for this session")
        _owners[key] = (run_id, task)
    try:
        yield
    finally:
        with _lock:
            if _owners.get(key) == (run_id, task):
                del _owners[key]
