"""准备单次请求中模型可见的上下文。"""

from dataclasses import dataclass
import json
from typing import Any


class ContextWindowExceeded(RuntimeError):
    """即使保留最少的请求内容，也没有空间生成回复。"""

    def __init__(self, input_tokens: int, window_tokens: int):
        """记录无法容纳请求时的输入估算与上下文上限。"""
        self.input_tokens = input_tokens
        self.window_tokens = window_tokens
        super().__init__(
            f"context_window_exceeded: estimated input {input_tokens} tokens leaves "
            f"no output room in a {window_tokens}-token window"
        )


@dataclass(frozen=True)
class ModelRequest:
    messages: list[dict]
    input_estimate: int
    max_tokens: int


def estimate_text_tokens(text: str) -> int:
    """从文本长度估算模型 token 数。"""
    if text.isascii():
        return (len(text) + 3) // 4
    ascii_chars = sum(char.isascii() for char in text)
    return (ascii_chars + 3) // 4 + len(text) - ascii_chars


def estimate_payload_tokens(payload: Any) -> int:
    """将结构化载荷转成文本后估算 token 数。"""
    return estimate_text_tokens(json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")))


def _limit_tool_output(message: dict, limit: int) -> dict:
    """限制模型可见的单条工具输出，保留无需截断的消息。"""
    content = message.get("content")
    if message.get("role") != "tool" or not isinstance(content, str) or len(content) <= limit:
        return message
    artifact_id = message.get("tool_artifact_id")
    if isinstance(artifact_id, str):
        reference = f"Artifact {artifact_id}"
        if len(reference) <= limit and content.startswith(reference):
            return {**message, "content": reference}
    marker = "\n[Tool output truncated]"
    return {**message, "content": content[:max(0, limit - len(marker))] + marker}


def prepare_model_request(
    messages: list[dict],
    system: str,
    tools: list[dict] | None,
    max_tokens: int,
    *,
    window_tokens: int,
    tool_output_chars: int,
    trim_history: bool = True,
) -> ModelRequest:
    """限制请求大小，保留原有会话历史。"""
    visible = [_limit_tool_output(message, tool_output_chars) for message in messages]
    estimate = estimate_payload_tokens((system, visible, tools))
    if estimate + max_tokens <= window_tokens:
        return ModelRequest(visible, estimate, max_tokens)

    # 用户回答和助手的提问属于同一对话轮次。
    starts = [0]
    if trim_history:
        starts.extend(
            index for index, message in enumerate(visible)
            if index and message.get("role") == "user" and not message.get("answer_to_question_id")
        )
    if len(starts) == 1:
        if estimate >= window_tokens:
            raise ContextWindowExceeded(estimate, window_tokens)
        return ModelRequest(visible, estimate, window_tokens - estimate)

    instructions = [
        (index, message) for index, message in enumerate(visible)
        if message.get("role") in ("system", "developer")
    ]

    def suffix(start: int) -> ModelRequest:
        """构造由固定消息与指定位置之后的完整对话轮次组成的候选消息列表。"""
        kept = [message for index, message in instructions if index < start] + visible[start:]
        return ModelRequest(kept, estimate_payload_tokens((system, kept, tools)), max_tokens)

    newest = suffix(starts[-1])
    headroom = min(max_tokens, window_tokens - newest.input_estimate)
    if headroom <= 0:
        raise ContextWindowExceeded(newest.input_estimate, window_tokens)

    # 找出能留足输出空间的最早完整轮次边界。
    best = newest
    low, high = 1, len(starts) - 2
    while low <= high:
        middle = (low + high) // 2
        candidate = suffix(starts[middle])
        if candidate.input_estimate + headroom <= window_tokens:
            best = candidate
            high = middle - 1
        else:
            low = middle + 1
    return ModelRequest(best.messages, best.input_estimate, headroom)
