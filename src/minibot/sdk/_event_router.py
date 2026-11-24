"""SDK 流式输出的内部事件路由。"""

from __future__ import annotations

import asyncio
import inspect
import threading
from typing import Any, Awaitable, Callable

from ..events import EventSink, StreamEvent


class RouterEventSink(EventSink):
    """如果有活跃队列，将收到的事件转发到该队列。"""

    def __init__(self) -> None:
        """初始化事件队列、旁路回调和用于同步路由状态的锁。"""
        self._queue: "asyncio.Queue[StreamEvent] | None" = None
        self._tap: "Callable[[StreamEvent], Awaitable[Any] | Any] | None" = None
        self._lock = threading.Lock()

    async def set_queue(self, queue: "asyncio.Queue[StreamEvent] | None") -> None:
        """切换接收流式事件的队列，传入 None 时清除当前订阅。"""
        with self._lock:
            self._queue = queue

    def detach_queue(self, queue: asyncio.Queue[StreamEvent]) -> None:
        """解除指定队列的订阅，队列已满时唤醒可能阻塞的生产者。"""
        with self._lock:
            if self._queue is queue:
                self._queue = None
        # 唤醒因事件队列已满而等待写入的生产者。
        if queue.full():
            queue.get_nowait()

    async def set_tap(
        self,
        tap: "Callable[[StreamEvent], Awaitable[Any] | Any] | None",
    ) -> None:
        """设置或清除接收事件的旁路回调，例如会话持久化处理器。"""
        with self._lock:
            self._tap = tap

    async def emit(self, event: StreamEvent) -> None:
        """先调用旁路回调，再将事件送入当前订阅队列。"""
        with self._lock:
            queue = self._queue
            tap = self._tap
        if tap is not None:
            result = tap(event)
            if inspect.isawaitable(result):
                await result
        if queue is None:
            return
        await queue.put(event)
