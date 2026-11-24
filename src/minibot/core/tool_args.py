"""用于解析模型工具调用参数的辅助函数。"""

from __future__ import annotations

import json
from typing import Any


def _strip_fenced_json(text: str) -> str:
    """如果存在 JSON 围栏代码块，去掉外层围栏。"""
    candidate = text.strip()
    if not (candidate.startswith("```") and candidate.endswith("```")):
        return candidate

    lines = candidate.splitlines()
    if len(lines) < 2:
        return candidate
    if lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return candidate


def parse_tool_arguments(raw: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """解析模型输出中的工具参数。

    返回 `(parsed_dict, note)`。
    - 无法恢复时，`parsed_dict` 为 `None`。
    - `note` 为警告或错误详情，正常解析时为 `None`。
    """
    if raw is None:
        return {}, None

    text = _strip_fenced_json(raw)
    if not text:
        return {}, None

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        decoder = json.JSONDecoder()
        try:
            parsed, end = decoder.raw_decode(text)
        except json.JSONDecodeError:
            return None, f"{exc.msg} at line {exc.lineno} column {exc.colno}"

        trailing = text[end:].strip()
        if not isinstance(parsed, dict):
            return None, f"arguments must be JSON object, got {type(parsed).__name__}"
        if trailing:
            return parsed, "Trailing content after JSON object was ignored"
        return parsed, None

    if not isinstance(parsed, dict):
        return None, f"arguments must be JSON object, got {type(parsed).__name__}"
    return parsed, None
