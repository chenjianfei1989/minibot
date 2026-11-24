"""为可感知团队的工具执行传递上下文。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from .runtime import TeamRuntime


@dataclass
class TeamExecutionContext:
    """工具可访问的单次执行团队上下文。"""

    role: str
    team_id: str | None
    member_id: str | None
    runtime: "TeamRuntime | None" = None


_CTX: ContextVar[TeamExecutionContext | None] = ContextVar(
    "minibot_team_execution_context",
    default=None,
)


@contextmanager
def team_execution_context(ctx: TeamExecutionContext | None) -> Iterator[None]:
    """临时为当前任务绑定执行上下文。"""
    token = _CTX.set(ctx)
    try:
        yield
    finally:
        _CTX.reset(token)


def get_team_execution_context() -> TeamExecutionContext | None:
    """获取当前团队执行上下文。"""
    return _CTX.get()
