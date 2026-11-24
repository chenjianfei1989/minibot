"""按次运行记录允许列表中的执行字段，与完整的流式事件载荷分开。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any, Literal, TextIO
import uuid

from .events import StreamEvent
from .core.artifacts import ArtifactEvent, ArtifactMetadata
from .core.model_context import ContextWindowExceeded
from .core.runtime_budget import RuntimeBudgetExceeded
from .tools.result import ToolOutcome

RunStatus = Literal[
    "completed", "failed", "interrupted", "waiting_for_user", "budget_exceeded", "context_window_exceeded",
]
SubagentStatus = Literal["completed", "failed", "interrupted", "budget_exceeded", "context_window_exceeded"]


@dataclass(frozen=True)
class Invocation:
    id: str
    call_id: str
    name: str
    started: float


@dataclass(frozen=True)
class _ModelAttempt:
    id: str
    started: float


class SubagentTrace:
    """单次内置 Task 调用中的顺序操作。"""

    def __init__(self, trace: RunTrace, parent: Invocation, agent_type: str) -> None:
        """绑定父运行和父调用信息，建立子 Agent 的追踪作用域。"""
        self._trace = trace
        self.run_id = uuid.uuid4().hex
        self._identity = {"child_run_id": self.run_id, "parent_invocation_id": parent.id}
        self._started = time.monotonic()
        self._pending: Invocation | _ModelAttempt | None = None
        self._write("subagent_start", agent_type=agent_type)

    def _write(self, event: str, **fields: Any) -> None:
        """附上子运行标识后写入一条追踪事件。"""
        self._trace._write(event, **self._identity, **fields)

    def observe_artifact(self, event: ArtifactEvent, metadata: ArtifactMetadata) -> None:
        """记录归属于当前子 Agent 调用的产物操作。"""
        invocation = self._pending
        if not isinstance(invocation, Invocation):
            return
        self._write(
            event, invocation_id=invocation.id, artifact_id=metadata.artifact_id,
            artifact_run_id=metadata.run_id, artifact_tool_name=metadata.tool_name,
            size_bytes=metadata.size_bytes, content_type=metadata.content_type,
            **({"workspace_id": metadata.workspace_id} if metadata.workspace_id is not None else {}),
        )

    def start_model(self) -> None:
        """创建一次子 Agent 模型请求的标识并记录开始时间。"""
        attempt = _ModelAttempt(uuid.uuid4().hex, time.monotonic())
        self._pending = attempt
        self._write("subagent_model_start", invocation_id=attempt.id)

    def finish_model(self, usage: Any = None, *, status: SubagentStatus = "completed") -> None:
        """结束当前模型请求的追踪，保存状态与可用的用量信息。"""
        attempt = self._pending
        if not isinstance(attempt, _ModelAttempt):
            return
        self._pending = None
        counts = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
            if type(value) is int and value >= 0:
                counts[key] = value
        fields = {"usage": counts} if counts else {}
        self._write(
            "subagent_model_end", invocation_id=attempt.id, status=status,
            duration_ms=(time.monotonic() - attempt.started) * 1000, **fields,
        )

    def start_tool(self, call_id: str, name: str) -> None:
        """创建并记录一次子 Agent 工具调用的起始信息。"""
        invocation = Invocation(
            uuid.uuid4().hex,
            call_id if isinstance(call_id, str) else "",
            name if isinstance(name, str) else "",
            time.monotonic(),
        )
        self._pending = invocation
        self._write(
            "subagent_tool_start", invocation_id=invocation.id,
            tool_call_id=invocation.call_id, tool_name=invocation.name,
        )

    def finish_tool(self, outcome: ToolOutcome | None = None, *, status: str = "error") -> None:
        """结束当前子 Agent 工具调用的追踪并记录执行结果。"""
        invocation = self._pending
        if not isinstance(invocation, Invocation):
            return
        self._pending = None
        fields: dict[str, Any] = {}
        if outcome is not None:
            if type(outcome.exit_code) is int:
                fields["exit_code"] = outcome.exit_code
            if outcome.hook_error is not None and outcome.hook_phase in ("pre", "post"):
                fields["hook_phase"] = outcome.hook_phase
        self._write(
            "subagent_tool_end", invocation_id=invocation.id,
            tool_call_id=invocation.call_id, tool_name=invocation.name,
            status=outcome.status if outcome is not None else status,
            is_error=outcome.is_error if outcome is not None else True,
            duration_ms=(time.monotonic() - invocation.started) * 1000, **fields,
        )

    def close(self, status: SubagentStatus, *, budget_limit: str | None = None) -> None:
        """结束追踪中尚未关闭的模型或工具调用并记录子运行状态。"""
        self.finish_model(status=status)
        tool_status = "timeout" if budget_limit == "max_wall_time" else (
            "interrupted" if status == "interrupted" else "error"
        )
        self.finish_tool(status=tool_status)
        fields = {"budget_limit": budget_limit} if budget_limit is not None else {}
        self._write(
            "subagent_end", status=status, duration_ms=(time.monotonic() - self._started) * 1000, **fields,
        )


class RunTrace:
    """每个生产者独占一个文件。写入失败时仍保留原执行结果。"""

    def __init__(
        self, directory: Path, session_id: str, *, run_id: str | None = None,
        parent_run_id: str | None = None,
    ) -> None:
        """初始化运行标识、计时和追踪文件。"""
        self.run_id = uuid.UUID(run_id).hex if run_id else uuid.uuid4().hex
        self.session_id = session_id
        self.started = time.monotonic()
        self.sequence = 0
        self.pending: Invocation | None = None
        self._subagent: SubagentTrace | None = None
        self.waiting = False
        self._file: TextIO | None = None
        try:
            directory.mkdir(parents=True, exist_ok=True)
            self._file = (directory / f"{self.run_id}.jsonl").open("x", encoding="utf-8")
        except (OSError, ValueError):
            self._disable()
        self._write(
            "run_start", scope="agent_tools", parent_run_id=parent_run_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    def _disable(self) -> None:
        """记录诊断并禁用当前运行的追踪写入。"""
        logging.getLogger(__name__).warning("Execution trace unavailable; recording disabled for this run.")
        file, self._file = self._file, None
        if file is not None:
            try:
                file.close()
            except (OSError, ValueError):
                pass

    def _write(self, event: str, **fields: Any) -> None:
        """把规范化后的事件记录追加到当前追踪文件。"""
        if self._file is None:
            return
        self.sequence += 1
        record = {
            "version": 1, "event": event, "run_id": self.run_id,
            "session_id": self.session_id, "sequence": self.sequence,
            "elapsed_ms": (time.monotonic() - self.started) * 1000,
            **fields,
        }
        try:
            self._file.write(json.dumps(record, ensure_ascii=True) + "\n")
            self._file.flush()
        except (OSError, ValueError):
            self._disable()

    def finish_tool(self, *, status: str, is_error: bool, **fields: Any) -> None:
        """结束当前父级工具调用并写入结束状态及耗时。"""
        invocation, self.pending = self.pending, None
        if invocation is None:
            return
        if self._subagent is not None:
            if status == "timeout":
                self._finish_subagent("budget_exceeded", budget_limit="max_wall_time")
            else:
                self._finish_subagent("interrupted")
        self._write(
            "tool_end", invocation_id=invocation.id, tool_call_id=invocation.call_id,
            tool_name=invocation.name, status=status, is_error=is_error,
            duration_ms=(time.monotonic() - invocation.started) * 1000, **fields,
        )

    def _finish_subagent(self, status: SubagentStatus, *, budget_limit: str | None = None) -> None:
        """取出当前子追踪并按给定状态结束它。"""
        child, self._subagent = self._subagent, None
        if child is not None:
            child.close(status, budget_limit=budget_limit)

    def link_durable_child(self, child_run_id: str, parent_step_id: str, agent_type: str) -> None:
        """将持久化子运行标识关联到当前父工具调用。"""
        invocation = self.pending
        self._write(
            "durable_child", child_run_id=child_run_id, parent_step_id=parent_step_id,
            agent_type=agent_type, parent_invocation_id=invocation.id if invocation is not None else None,
        )

    @contextmanager
    def subagent(self, agent_type: str) -> Iterator[SubagentTrace | None]:
        """为当前委派调用建立并管理子 Agent 追踪上下文。"""
        parent = self.pending
        if self._file is None or parent is None or parent.name != "Task" or self._subagent is not None:
            yield None
            return
        child = SubagentTrace(self, parent, agent_type)
        self._subagent = child
        try:
            yield child
        except (asyncio.CancelledError, KeyboardInterrupt):
            # 外层 Task 能区分共享时间预算超时和用户取消。
            raise
        except ContextWindowExceeded:
            self._finish_subagent("context_window_exceeded")
            raise
        except RuntimeBudgetExceeded as exc:
            self._finish_subagent("budget_exceeded", budget_limit=exc.limit)
            raise
        except BaseException:
            self._finish_subagent("failed")
            raise
        else:
            self._finish_subagent("completed")

    def observe_artifact(self, event: ArtifactEvent, metadata: ArtifactMetadata) -> None:
        """记录父运行工具调用中的产物操作。"""
        invocation = self.pending
        if not isinstance(invocation, Invocation):
            return
        self._write(
            event, invocation_id=invocation.id, artifact_id=metadata.artifact_id,
            artifact_run_id=metadata.run_id, artifact_tool_name=metadata.tool_name,
            size_bytes=metadata.size_bytes, content_type=metadata.content_type,
            **({"workspace_id": metadata.workspace_id} if metadata.workspace_id is not None else {}),
        )

    def observe(self, event: StreamEvent) -> None:
        """将 Agent 发出的结构化事件转换为支持的追踪记录。"""
        kind = event.get("type")
        if kind == "tool_call":
            invocation = Invocation(
                uuid.uuid4().hex, event.get("tool_call_id", ""),
                event.get("tool_name", ""), time.monotonic(),
            )
            self.pending = invocation
            self._write(
                "tool_start", invocation_id=invocation.id,
                tool_call_id=invocation.call_id, tool_name=invocation.name,
            )
        elif kind == "tool_result":
            fields: dict[str, Any] = {}
            if "tool_exit_code" in event:
                fields["exit_code"] = event["tool_exit_code"]
            if "tool_hook_phase" in event:
                fields["hook_phase"] = event["tool_hook_phase"]
            self.finish_tool(
                status=event.get("tool_status", "error"),
                is_error=event.get("is_error", True), **fields,
            )
        elif kind == "tool_approval_resolved":
            self._write(
                "tool_approval", approval_id=event["approval_id"], tool_name=event["tool_name"],
                approved=event["approved"], source=event["approval_source"],
            )
        elif kind == "ask_user_question":
            self.finish_tool(status="success", is_error=False)
            self.waiting = True
            self._write("run_waiting")
        elif kind == "ask_user_answer_received":
            self.waiting = False
            self._write("run_resumed")

    def close(self, status: RunStatus, *, budget_limit: str | None = None) -> None:
        """写入运行结束状态，清理未结束的调用和追踪资源。"""
        self.finish_tool(status="interrupted" if status == "interrupted" else "error", is_error=True)
        fields = {"budget_limit": budget_limit} if budget_limit is not None else {}
        self._write("run_end", status=status, duration_ms=(time.monotonic() - self.started) * 1000, **fields)
        file, self._file = self._file, None
        if file is not None:
            try:
                file.close()
            except (OSError, ValueError):
                self._disable()
