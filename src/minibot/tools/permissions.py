"""单次工具调用在执行层适用的策略与审批。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from fnmatch import fnmatchcase
import json
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from ..config.schema import ToolPermissionsConfig
from .base import BaseTool
from .builtin.file import EditFileTool, ListDirTool, ReadFileTool, WorkspaceFileTool, WriteFileTool
from .builtin.workspace_backend import WorkspacePath

ApprovalSource = Literal["policy", "human", "auto_review"]
ReviewDecision = Literal["approve", "deny", "ask"]
_FILE_TYPES = (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool)
_WRITE_TYPES = (WriteFileTool, EditFileTool)
_MAX_REVIEW_INPUT = 4_000


@dataclass(frozen=True)
class ToolApprovalRequest:
    approval_id: str
    tool_name: str
    actor: str
    preview: str


ToolApprovalHandler = Callable[[ToolApprovalRequest], Awaitable[bool]]
ToolReviewer = Callable[[str], Awaitable[ReviewDecision]]
ApprovalObserver = Callable[[ToolApprovalRequest, bool, ApprovalSource], Awaitable[None]]


def parse_review(text: str) -> ReviewDecision:
    """要求给出单个审批决定，无需附加说明。"""
    try:
        result = json.loads(text, object_pairs_hook=list)
    except (ValueError, RecursionError):
        return "ask"
    if result == [("decision", "approve")]:
        return "approve"
    if result == [("decision", "deny")]:
        return "deny"
    return "ask"


@dataclass(frozen=True)
class ApprovedCall:
    args: dict[str, Any]
    file: WorkspacePath | None = None
    requires_active_run: bool = False

    def still_targets(self, tool: BaseTool) -> bool:
        """重新解析文件目标，确认待执行参数仍指向批准时的目标。"""
        return self.file is None or _resolve_target(tool, self.args) == self.file


def _resolve_target(tool: BaseTool, args: dict[str, Any]) -> WorkspacePath | None:
    """从工具参数和后端权限接口取得文件目标。"""
    path = args.get("path")
    if not isinstance(tool, WorkspaceFileTool) or not isinstance(path, str) or not path:
        return None
    try:
        return tool.permission_target(path)
    except (OSError, RuntimeError, ValueError):
        return None


@dataclass
class PermissionRun:
    policy: ToolPermissionsConfig
    human: ToolApprovalHandler | None
    review: ToolReviewer
    observe: ApprovalObserver
    user_intent: str | None
    active: bool = True

    async def authorize(
        self, name: str, args: dict[str, Any], tool: BaseTool, actor: str,
    ) -> ApprovedCall | None:
        """按工具规则和默认策略作出权限决定，必要时发起审批。"""
        choice = self.policy.rules.get(name, self.policy.default)
        target = None
        if type(tool) in _FILE_TYPES:
            target = _resolve_target(tool, args)
            if target is None:
                choice = "deny"
        # 模型给出的工具参数是 JSON。此快照独立于原始输入，
        # 也独立于之后传给钩子的任何可变副本。
        try:
            encoded = json.dumps(args, ensure_ascii=True, allow_nan=False, indent=2)
            arguments = json.loads(encoded)
        except (TypeError, ValueError, RecursionError):
            return None

        if target is not None:
            arguments["path"] = target.relative
            encoded = json.dumps(arguments, ensure_ascii=True, allow_nan=False, indent=2)

        call = ApprovedCall(arguments, target, requires_active_run=choice == "ask")
        if choice == "allow":
            return call
        if not self.active:
            return None
        request = ToolApprovalRequest(uuid4().hex, name, actor, encoded)
        if choice == "deny":
            await self.observe(request, False, "policy")
            return None

        # 审核器只能批准显式配置的路径，
        # 且不能批准可能产生外部副作用的通用工具。
        if self._can_review(tool, call, encoded):
            brief = json.dumps(
                {"user_request": self.user_intent, "tool": name, "arguments": arguments},
                ensure_ascii=True, allow_nan=False,
            )
            if len(brief) <= _MAX_REVIEW_INPUT:
                decision = await self.review(brief)
                if decision != "ask":
                    approved = decision == "approve"
                    if self.active:
                        await self.observe(request, approved, "auto_review")
                    return call if approved and self.active else None

        approved = False
        if self.human is not None and self.active:
            try:
                async with asyncio.timeout(self.policy.timeout):
                    approved = (await self.human(request)) is True
            except TimeoutError:
                pass
        if self.active:
            await self.observe(request, approved, "human")
        return call if approved and self.active else None

    def _can_review(self, tool: BaseTool, call: ApprovedCall, preview: str) -> bool:
        """判断当前工具和文件目标是否满足模型审核的范围限制。"""
        if (
            self.policy.mode != "auto_review" or not self.user_intent or type(tool) not in _WRITE_TYPES
            or call.file is None or len(preview) > _MAX_REVIEW_INPUT
        ):
            return False
        target = PurePosixPath(call.args["path"])
        if any(part.startswith(".") for part in target.parts):
            return False
        return any(fnmatchcase(target.as_posix(), pattern) for pattern in self.policy.auto_review_paths)


current_permissions: ContextVar[PermissionRun | None] = ContextVar("tool_permissions", default=None)
