"""MiniBot 类型定义。"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ContentBlock:
    """消息中的一个内容块。"""
    type: Literal["text", "tool_use", "tool_result"]
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None
    tool_use_id: str | None = None
    content: str | None = None


@dataclass
class Message:
    """会话中的一条消息。"""
    role: Literal["user", "assistant", "system"]
    content: str | list[ContentBlock | dict]


@dataclass
class ToolCall:
    """模型发出的一次工具调用请求。"""
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    """一次工具执行的结果。"""
    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass
class ToolDefinition:
    """提供给 API 的工具定义。"""
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_dict(self) -> dict:
        """转换为兼容 OpenAI 或 GLM API 的字典。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }
