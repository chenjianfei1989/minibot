"""SDK 公共类型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChatResult:
    session_id: str
    messages: list[dict[str, Any]]
    assistant_text: str
    usage: dict[str, int] | None = None

