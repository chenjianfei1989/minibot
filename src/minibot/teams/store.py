"""保存单个活跃团队状态的内存存储。"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from .models import (
    FileLock,
    MemberStatus,
    TaskStatus,
    Team,
    TeamMember,
    TeamMessage,
    TeamTask,
    as_dict,
    utc_now_iso,
)


class TeamStore:
    """保存团队成员、消息、任务、锁和事件。"""

    def __init__(self, log_dir: Path):
        """初始化当前团队的内存状态、日志目录和并发协调资源。"""
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._team: Team | None = None
        self._messages: list[TeamMessage] = []
        self._tasks: dict[str, TeamTask] = {}
        self._mailboxes: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._file_locks: dict[str, FileLock] = {}
        self._workspace_lock_owner: str | None = None
        self._lock = asyncio.Lock()
        self._log_file: Path | None = None

    @property
    def has_team(self) -> bool:
        """判断当前存储是否已有团队实例。"""
        return self._team is not None

    @property
    def team(self) -> Team | None:
        """返回当前团队对象。"""
        return self._team

    async def create_team(
        self,
        *,
        team_name: str,
        lead_id: str,
        teammate_ids: list[str],
    ) -> Team:
        """创建一个新团队。"""
        async with self._lock:
            if self._team is not None:
                raise ValueError("A team is already active in this session")

            team_id = f"team-{uuid.uuid4().hex[:8]}"
            members: dict[str, TeamMember] = {
                lead_id: TeamMember(
                    member_id=lead_id,
                    name=lead_id,
                    role="lead",
                    status=MemberStatus.IDLE,
                )
            }
            for member_id in teammate_ids:
                members[member_id] = TeamMember(
                    member_id=member_id,
                    name=member_id,
                    role="teammate",
                    status=MemberStatus.IDLE,
                )
            self._team = Team(
                team_id=team_id,
                name=team_name,
                lead_id=lead_id,
                members=members,
            )
            self._messages = []
            self._tasks = {}
            self._mailboxes = {}
            self._events = asyncio.Queue()
            self._file_locks = {}
            self._workspace_lock_owner = None
            self._log_file = self.log_dir / f"{team_id}.jsonl"

            event = {
                "type": "team_created",
                "team_id": team_id,
                "team_name": team_name,
                "member_count": len(members),
                "created_at": utc_now_iso(),
            }
            self._emit_event_unlocked(event)
            return self._team

    async def clear_team(self) -> None:
        """清除当前团队的所有状态。"""
        async with self._lock:
            self._team = None
            self._messages = []
            self._tasks = {}
            self._mailboxes = {}
            self._events = asyncio.Queue()
            self._file_locks = {}
            self._workspace_lock_owner = None
            self._log_file = None

    async def register_mailbox(self, member_id: str) -> asyncio.Queue[dict[str, Any]]:
        """创建或返回指定成员的收件队列。"""
        async with self._lock:
            if self._team is None:
                raise ValueError("No active team")
            if member_id not in self._team.members:
                raise ValueError(f"Unknown member: {member_id}")
            queue = self._mailboxes.get(member_id)
            if queue is None:
                queue = asyncio.Queue()
                self._mailboxes[member_id] = queue
            return queue

    async def enqueue_mail(self, member_id: str, item: dict[str, Any]) -> None:
        """向成员的收件箱推送一条消息封装。"""
        async with self._lock:
            queue = self._mailboxes.get(member_id)
        if queue is None:
            raise ValueError(f"Mailbox not found for member: {member_id}")
        await queue.put(item)

    async def add_message(
        self,
        *,
        sender_id: str,
        recipient_id: str,
        content: str,
        kind: str,
    ) -> TeamMessage:
        """持久化一条团队消息。"""
        async with self._lock:
            if self._team is None:
                raise ValueError("No active team")
            if sender_id not in self._team.members:
                raise ValueError(f"Unknown sender: {sender_id}")
            if recipient_id not in self._team.members:
                raise ValueError(f"Unknown recipient: {recipient_id}")

            msg = TeamMessage(
                message_id=f"msg-{uuid.uuid4().hex[:10]}",
                team_id=self._team.team_id,
                sender_id=sender_id,
                recipient_id=recipient_id,
                content=content,
                kind=kind,
            )
            self._messages.append(msg)
            self._emit_event_unlocked(
                {
                    "type": "message",
                    "kind": kind,
                    "team_id": self._team.team_id,
                    "message_id": msg.message_id,
                    "sender_id": sender_id,
                    "recipient_id": recipient_id,
                    "content": content,
                    "created_at": msg.created_at,
                }
            )
            return msg

    async def list_members(self) -> list[TeamMember]:
        """返回当前成员。"""
        async with self._lock:
            if self._team is None:
                return []
            return list(self._team.members.values())

    async def set_member_status(
        self,
        member_id: str,
        status: MemberStatus,
        *,
        last_error: str | None = None,
    ) -> None:
        """更新一名成员的状态。"""
        async with self._lock:
            if self._team is None:
                return
            member = self._team.members.get(member_id)
            if member is None:
                return
            member.status = status
            member.last_active_at = utc_now_iso()
            member.last_error = last_error

    async def create_task(
        self,
        *,
        title: str,
        details: str,
        created_by: str,
        assignee_id: str | None = None,
    ) -> TeamTask:
        """创建一项共享任务。"""
        async with self._lock:
            if self._team is None:
                raise ValueError("No active team")
            if created_by not in self._team.members:
                raise ValueError(f"Unknown creator: {created_by}")
            if assignee_id is not None and assignee_id not in self._team.members:
                raise ValueError(f"Unknown assignee: {assignee_id}")

            task = TeamTask(
                task_id=f"task-{uuid.uuid4().hex[:10]}",
                team_id=self._team.team_id,
                title=title,
                details=details,
                created_by=created_by,
                assignee_id=assignee_id,
            )
            self._tasks[task.task_id] = task
            self._emit_event_unlocked(
                {
                    "type": "task_created",
                    "team_id": self._team.team_id,
                    "task": as_dict(task),
                }
            )
            return task

    async def list_tasks(self) -> list[TeamTask]:
        """按创建顺序列出任务。"""
        async with self._lock:
            return list(self._tasks.values())

    async def assign_task(self, task_id: str, assignee_id: str) -> TeamTask:
        """将任务分配给一名成员。"""
        async with self._lock:
            if self._team is None:
                raise ValueError("No active team")
            task = self._tasks.get(task_id)
            if task is None:
                raise ValueError(f"Unknown task: {task_id}")
            if assignee_id not in self._team.members:
                raise ValueError(f"Unknown member: {assignee_id}")
            task.assignee_id = assignee_id
            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.IN_PROGRESS
            self._emit_event_unlocked(
                {
                    "type": "task_assigned",
                    "team_id": self._team.team_id,
                    "task_id": task_id,
                    "assignee_id": assignee_id,
                }
            )
            return task

    async def claim_task(self, member_id: str, task_id: str | None = None) -> TeamTask | None:
        """为成员认领第一个可用任务。"""
        async with self._lock:
            if self._team is None:
                raise ValueError("No active team")
            if member_id not in self._team.members:
                raise ValueError(f"Unknown member: {member_id}")

            if task_id is not None:
                task = self._tasks.get(task_id)
                if task is None:
                    raise ValueError(f"Unknown task: {task_id}")
                candidates = [task]
            else:
                candidates = list(self._tasks.values())

            for task in candidates:
                if task.status == TaskStatus.COMPLETED:
                    continue
                if task.assignee_id not in (None, member_id):
                    continue
                task.assignee_id = member_id
                task.status = TaskStatus.IN_PROGRESS
                self._emit_event_unlocked(
                    {
                        "type": "task_claimed",
                        "team_id": self._team.team_id,
                        "task_id": task.task_id,
                        "member_id": member_id,
                    }
                )
                return task
            return None

    async def complete_task(
        self,
        *,
        task_id: str,
        completed_by: str,
        note: str | None = None,
    ) -> TeamTask:
        """将任务标记为已完成。"""
        async with self._lock:
            if self._team is None:
                raise ValueError("No active team")
            task = self._tasks.get(task_id)
            if task is None:
                raise ValueError(f"Unknown task: {task_id}")
            task.status = TaskStatus.COMPLETED
            task.completed_by = completed_by
            task.completed_at = utc_now_iso()
            task.completion_note = note
            self._emit_event_unlocked(
                {
                    "type": "task_completed",
                    "team_id": self._team.team_id,
                    "task_id": task_id,
                    "completed_by": completed_by,
                    "note": note,
                    "completed_at": task.completed_at,
                }
            )
            return task

    async def acquire_file_lock(self, *, path: str, member_id: str) -> tuple[bool, str | None]:
        """为一个文件路径获取锁。"""
        async with self._lock:
            if self._team is None:
                raise ValueError("No active team")
            if member_id not in self._team.members:
                raise ValueError(f"Unknown member: {member_id}")
            existing = self._file_locks.get(path)
            if existing is None:
                self._file_locks[path] = FileLock(path=path, owner_member_id=member_id)
                return True, None
            if existing.owner_member_id == member_id:
                return True, None
            return False, existing.owner_member_id

    async def acquire_workspace_lock(self, *, member_id: str) -> tuple[bool, str | None]:
        """获取覆盖整个工作区的锁，以避免不同操作之间发生冲突。"""
        async with self._lock:
            if self._team is None:
                raise ValueError("No active team")
            if member_id not in self._team.members:
                raise ValueError(f"Unknown member: {member_id}")
            if self._workspace_lock_owner in (None, member_id):
                self._workspace_lock_owner = member_id
                return True, None
            return False, self._workspace_lock_owner

    async def release_member_locks(self, member_id: str) -> None:
        """释放一名成员持有的所有文件锁和工作区锁。"""
        async with self._lock:
            to_remove = [
                path for path, lock in self._file_locks.items() if lock.owner_member_id == member_id
            ]
            for path in to_remove:
                self._file_locks.pop(path, None)
            if self._workspace_lock_owner == member_id:
                self._workspace_lock_owner = None

    async def emit_event(self, event: dict[str, Any]) -> None:
        """发布一条事件记录。"""
        async with self._lock:
            self._emit_event_unlocked(event)

    def _emit_event_unlocked(self, event: dict[str, Any]) -> None:
        """在调用方已持有锁时发布团队事件。"""
        event = dict(event)
        event.setdefault("timestamp", utc_now_iso())
        self._events.put_nowait(event)
        if self._log_file is not None:
            try:
                with self._log_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except Exception:
                pass

    async def wait_events(self, timeout_sec: int, max_events: int = 20) -> list[dict[str, Any]]:
        """等待事件，可用时至少返回一条。"""
        if max_events < 1:
            max_events = 1

        first = await asyncio.wait_for(self._events.get(), timeout=timeout_sec)
        items = [first]
        while len(items) < max_events:
            try:
                items.append(self._events.get_nowait())
            except asyncio.QueueEmpty:
                break
        return items

    async def summary(self) -> dict[str, Any]:
        """供 /info 和调试使用的运行时摘要。"""
        async with self._lock:
            if self._team is None:
                return {"active": False}
            members = list(self._team.members.values())
            return {
                "active": True,
                "team_id": self._team.team_id,
                "name": self._team.name,
                "members": len(members),
                "running": sum(1 for m in members if m.status == MemberStatus.IN_PROGRESS),
                "tasks": len(self._tasks),
            }
