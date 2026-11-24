"""管理 Rich 可用性与共享控制台。"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console


def rich_enabled() -> bool:
    env = os.environ.get("MINIBOT_RICH", "1").strip().lower()
    if env in {"0", "false", "no", "off"}:
        return False
    try:
        if not sys.stdout.isatty():
            return False
    except Exception:
        return False
    try:
        import rich  # noqa: F401
    except Exception:
        return False
    return True


_CONSOLE: "Console | None" = None


def get_console() -> "Console":
    global _CONSOLE
    from .terminal import term_width

    desired_width = term_width()
    if _CONSOLE is not None and _CONSOLE.width == desired_width:
        return _CONSOLE
    from rich.console import Console

    # 此处不要启用 soft_wrap=True，因为它会禁用换行和裁剪，
    # 可能导致 Rich 面板或 Markdown 丢失长行内容。
    _CONSOLE = Console(highlight=False, soft_wrap=False, emoji=False, width=desired_width)
    return _CONSOLE
