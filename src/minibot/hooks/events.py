"""钩子事件定义。"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HookEvent(Enum):
    """可以触发钩子的事件。"""

    # 工具生命周期。
    PRE_TOOL_CALL = "pre_tool_call"
    POST_TOOL_CALL = "post_tool_call"

    # Agent 对话轮次生命周期。
    PRE_AGENT_TURN = "pre_agent_turn"
    POST_AGENT_TURN = "post_agent_turn"

    # 会话生命周期。
    SESSION_START = "session_start"
    SESSION_END = "session_end"

    # 技能加载。
    SKILL_LOAD = "skill_load"

    # 团队生命周期。
    TEAMMATE_IDLE = "teammate_idle"
    TASK_COMPLETED = "task_completed"


@dataclass
class HookContext:
    """钩子执行的基础上下文。"""

    event: HookEvent
    workdir: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallContext(HookContext):
    """工具调用钩子的上下文。"""

    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_result: str | None = None
    blocked: bool = False
    block_reason: str | None = None


@dataclass
class SessionContext(HookContext):
    """会话钩子的上下文。"""

    session_id: str = ""
    user_message: str | None = None


@dataclass
class SkillLoadContext(HookContext):
    """技能加载钩子的上下文。"""

    skill_name: str = ""
    skill_content: str | None = None


@dataclass
class TeamEventContext(HookContext):
    """团队相关钩子的上下文。"""

    team_member_id: str | None = None
    task_id: str | None = None
    detail: str | None = None


@dataclass
class HookResult:
    """钩子执行的结果。"""

    success: bool
    output: str | None = None
    error: str | None = None
    blocked: bool = False
    block_reason: str | None = None
    modified_context: dict[str, Any] | None = None
