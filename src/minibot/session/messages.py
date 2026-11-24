"""用于规范化持久化会话消息的辅助函数。"""

from __future__ import annotations

from typing import Any


def normalize_tool_calls(value: Any) -> list[dict[str, Any]]:
    """以 OpenAI 聊天补全消息的结构返回工具调用。"""
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            continue
        tool_id = str(raw.get("id") or f"tool-call-{index}")
        function = raw.get("function")
        if isinstance(function, dict):
            normalized.append(
                {
                    "id": tool_id,
                    "type": str(raw.get("type") or "function"),
                    "function": {
                        "name": str(function.get("name") or ""),
                        "arguments": str(function.get("arguments") or ""),
                    },
                }
            )
            continue

        normalized.append(
            {
                "id": tool_id,
                "type": "function",
                "function": {
                    "name": str(raw.get("name") or ""),
                    "arguments": str(raw.get("arguments") or ""),
                },
            }
        )
    return normalized


def normalize_session_message(message: dict[str, Any]) -> dict[str, Any]:
    """规范化恢复执行所需的持久化消息字段。"""
    normalized = dict(message)
    if "tool_calls" in normalized:
        tool_calls = normalize_tool_calls(normalized.get("tool_calls"))
        if tool_calls:
            normalized["tool_calls"] = tool_calls
        else:
            normalized.pop("tool_calls", None)
    return normalized
