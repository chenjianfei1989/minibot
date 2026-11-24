"""Agent 团队的数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now_iso() -> str:
    """ISO 8601 格式的 UTC 时间戳。"""
    return datetime.now(timezone.utc).isoformat()


class MemberStatus(str, Enum):
    """团队成员的生命周期状态。"""

    IDLE = "idle"
    IN_PROGRESS = "in_progress"
    STOPPED = "stopped"
    ERROR = "error"


class TaskStatus(str, Enum):
    """任务的生命周期状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class TeamMember:
    """单个团队成员。"""

    member_id: str
    name: str
    role: str  # 角色为 lead 或 teammate。
    status: MemberStatus = MemberStatus.IDLE
    created_at: str = field(default_factory=utc_now_iso)
    last_active_at: str = field(default_factory=utc_now_iso)
    last_error: str | None = None


@dataclass
class Team:
    """保存在内存中的团队定义。"""

    team_id: str
    name: str
    lead_id: str
    created_at: str = field(default_factory=utc_now_iso)
    members: dict[str, TeamMember] = field(default_factory=dict)


@dataclass
class TeamMessage:
    """团队成员之间的消息。"""

    message_id: str
    team_id: str
    sender_id: str
    recipient_id: str
    content: str
    created_at: str = field(default_factory=utc_now_iso)
    kind: str = "direct"  # 消息类型为 direct 或 broadcast。


@dataclass
class TeamTask:
    """共享任务板上的一项任务。"""

    task_id: str
    team_id: str
    title: str
    details: str
    created_by: str
    created_at: str = field(default_factory=utc_now_iso)
    status: TaskStatus = TaskStatus.PENDING
    assignee_id: str | None = None
    completed_by: str | None = None
    completed_at: str | None = None
    completion_note: str | None = None


@dataclass
class FileLock:
    """由队友持有的文件级锁。"""

    path: str
    owner_member_id: str
    acquired_at: str = field(default_factory=utc_now_iso)


def as_dict(obj: Any) -> dict[str, Any]:
    """将数据类转换为普通字典的辅助函数。"""
    from dataclasses import asdict

    return asdict(obj)
