"""采用模块化架构的 MiniBot，提供类似 Claude Code 的功能。"""

__version__ = "0.1.0"

from .sdk import Minibot  # noqa: E402

__all__ = ["Minibot", "__version__"]
