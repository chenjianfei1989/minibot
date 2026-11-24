"""流式输出和聊天集成使用的基础事件类型。

SDK、服务端和界面共用这里定义的简洁稳定的事件结构，彼此无需依赖终端渲染。
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal, NotRequired, Protocol, TypedDict

from .tools.result import ToolStatus


EventType = Literal[
    "assistant_start",
    "assistant_reasoning_delta",
    "assistant_delta",
    "assistant_end",
    "ask_user_question",
    "ask_user_answer_received",
    "todo_snapshot",
    "tool_call",
    "tool_result",
    "tool_approval_request",
    "tool_approval_resolved",
    "system",
]


class StreamEvent(TypedDict, total=False):
    """Agent 运行时发出的结构化事件。"""

    type: EventType
    session_id: str

    # 助手流式输出。
    message_id: str
    parent_user_message_id: str | None
    delta_text: str
    reasoning_text: str
    reasoning: str
    content: str
    finish_reason: str
    tool_calls: list[dict[str, Any]]
    usage: dict[str, int]
    context_usage: dict[str, int]
    context_compacted: bool
    todo: dict[str, Any]

    # 用户问答交互。
    question_id: str
    prompt: str
    options: list[dict[str, str]]
    allow_free_text: bool
    required: bool
    answer_text: str
    selected_option_value: str | None

    # 工具执行。
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]
    tool_output: str
    is_error: bool
    tool_status: ToolStatus
    tool_exit_code: int
    tool_artifact_id: str
    tool_hook_error: str
    tool_hook_phase: Literal["pre", "post"]
    note: str

    # 工具审批。
    approval_id: str
    approval_actor: str
    approval_preview: str
    approved: bool
    approval_source: Literal["policy", "human", "auto_review"]

    # 系统与状态事件。
    message: str
    data: dict[str, Any]


class EventSink(Protocol):
    async def emit(self, event: StreamEvent) -> None:
        """消费一条事件。"""


class NullEventSink:
    async def emit(self, event: StreamEvent) -> None:  # noqa: ARG002
        """忽略收到的事件，供无需消费结构化事件的调用方使用。"""
        return None


class AsyncQueueEventSink:
    """以 asyncio.Queue 为底层队列的事件接收器。"""

    def __init__(self, queue: "asyncio.Queue[StreamEvent]") -> None:
        """绑定用于接收流式事件的异步队列。"""
        self.queue = queue

    async def emit(self, event: StreamEvent) -> None:
        """将一条结构化事件放入绑定的队列。"""
        await self.queue.put(event)
