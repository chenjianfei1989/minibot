"""供开发者在代码中调用 MiniBot 的 SDK 封装。"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from pathlib import Path
import uuid
from typing import Any, AsyncIterator, Callable, Iterable, Iterator

from ..agent import Agent, UserInterruptedError
from ..config import Config, load_config
from ..config.workspace import require_outside_root, validate_workspace_runtime
from ..core.model_context import ContextWindowExceeded
from ..core.artifacts import ArtifactError
from ..core.run_store import ChildRun, DurableRunError, DurableRunPaused, RunState, RunStore, StepState
from ..core.runtime_budget import RuntimeBudgetExceeded
from ..events import StreamEvent
from ..file_checkpoints import FileCheckpoint, FileCheckpointError, GitFileCheckpoints, finish_file_operation
from ..session.manager import SessionManager
from ..session.messages import normalize_tool_calls
from ..subagents.deliverables import ChildArtifact, apply_child_artifact, parse_deliverable_paths
from ..subagents.durable import DurableSubagents
from ..tools.base import BaseTool
from ..tools.permissions import ToolApprovalHandler, ToolApprovalRequest

from ._active_streams import own_stream
from ._event_router import RouterEventSink
from .types import ChatResult


ToolInput = BaseTool | Callable[..., Any] | dict[str, Any]


def _has_running_loop() -> bool:
    """判断当前线程是否已有正在运行的 asyncio 事件循环，供同步入口检查。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _last_assistant_text(messages: list[dict[str, Any]]) -> str:
    """从后往前查找最近一条文本类型的助手消息，找不到时返回空字符串。"""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content")
            if isinstance(content, str):
                return content
    return ""


def _last_assistant_usage(messages: list[dict[str, Any]]) -> dict[str, int] | None:
    """返回最近一份非空的助手用量统计的副本，找不到时返回 None。"""
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        usage = msg.get("usage")
        if isinstance(usage, dict) and usage:
            return dict(usage)
    return None


def _last_user_message_id(messages: list[dict[str, Any]]) -> str | None:
    """从后往前查找最近一个有效的用户消息 ID，找不到时返回 None。"""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        message_id = msg.get("message_id")
        if isinstance(message_id, str) and message_id.strip():
            return message_id
    return None


def _new_message_id() -> str:
    """生成带有 msg- 前缀的消息 ID。"""
    return f"msg-{uuid.uuid4().hex[:12]}"


@dataclass
class _StreamPersistenceState:
    session_id: str
    stop_on_ask_user_question: bool = False
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    persisted_message_ids: set[str] = field(default_factory=set)
    assistant_contents: dict[str, str] = field(default_factory=dict)
    assistant_reasoning: dict[str, str] = field(default_factory=dict)
    assistant_parent_ids: dict[str, str | None] = field(default_factory=dict)
    question_message_ids: dict[str, str] = field(default_factory=dict)
    producer: asyncio.Task[None] | None = None
    approvals_cancelled: bool = False


class Minibot:
    """面向 SDK 调用方的 :class:`minibot.agent.Agent` 封装。"""

    def __init__(
        self,
        *,
        config: Config | None = None,
        workdir: str | Path | None = None,
        session_id: str | None = None,
        sessions_dir: str | Path | None = None,
        skills_dir: str | Path | Iterable[str | Path] | None = None,
        tools: list[ToolInput] | None = None,
        system_prompt: str | None = None,
        disabled_skills: Iterable[str] | None = None,
        allow_subagent_delegation: bool = True,
        allow_team_tools: bool = True,
        tool_approval_handler: ToolApprovalHandler | None = None,
        durable_execution: bool | None = None,
    ) -> None:
        """加载或接收配置，初始化会话、Agent 和事件路由，并注册传入的工具。

        传入 session_id 时使用指定会话，启用会话持久化后加载已有历史。
        system_prompt 作为附加提示词传给 Agent，durable_execution 可覆盖配置中的运行恢复设置。
        """
        if config is None:
            resolved_workdir = Path(workdir).resolve() if workdir is not None else None
            config = load_config(workdir=resolved_workdir)

        if durable_execution is not None:
            config = replace(config, durable_execution=durable_execution)

        if sessions_dir is not None:
            config.session.sessions_dir = str(Path(sessions_dir).expanduser().resolve())

        validate_workspace_runtime(config)
        if tools and config.workspace.restricted:
            raise ValueError("Custom Python tools are unavailable in a restricted Docker workspace")
        # SDK 和底层 Agent 共用的运行配置，已应用构造参数提供的覆盖项。
        self.config = config
        # 将 Agent 的结构化事件转发给流式消费者和持久化回调。
        self._event_router = RouterEventSink()
        # 管理会话历史和运行时状态。关闭会话持久化时为 None。
        self._session_manager = (
            SessionManager(Path(self.config.session.sessions_dir))
            if self.config.session.enabled
            else None
        )

        # 当前会话 ID。未指定时创建新会话，指定时使用对应的会话。
        self.session_id = self._resolve_session_id(session_id)
        # 当前会话在内存中的消息列表。启用会话持久化时，从存储加载历史。
        self.messages: list[dict[str, Any]] = (
            self._session_manager.load(self.session_id)
            if self._session_manager is not None
            else []
        )

        # 当前流式生成的中断队列。cancel() 通过它通知 Agent 停止。
        self._active_interrupt_queue: "asyncio.Queue[None] | None" = None
        # 当前仍在等待前端回答的问题，供 pending_question() 查询。
        self._pending_question: dict[str, Any] | None = None
        # 等待用户答案的异步结果，由 submit_user_answer() 完成。
        self._pending_question_future: "asyncio.Future[dict[str, Any]] | None" = None
        # 当前流式执行的状态，记录会话、运行 ID 以及已持久化的消息。
        self._active_stream: _StreamPersistenceState | None = None
        # 当前是否正在执行持久化片段，用于阻止并发生成和会话切换。
        self._active_durable_segment = False
        # 调用方注入的可选异步审批回调。未提供时，活跃流可通过审批事件等待答复。
        self._tool_approval_handler = tool_approval_handler
        # 按审批 ID 保存待决的异步结果，以便提交或取消对应审批。
        self._pending_tool_approvals: dict[str, asyncio.Future[bool]] = {}

        # 负责模型调用与工具执行的 Agent。SDK 将事件、提问和审批回调接入此实例。
        self.agent = Agent(
            config=self.config,
            session_id=self.session_id,
            extra_system_prompt=system_prompt,
            event_sink=self._event_router,
            skills_dir=skills_dir,
            disabled_skills=disabled_skills,
            allow_subagent_delegation=allow_subagent_delegation,
            allow_team_tools=allow_team_tools,
            ask_user_handler=self._wait_for_user_answer,
            tool_approval_handler=self._wait_for_tool_approval,
        )

        if tools:
            for tool in tools:
                self.register_tool(tool)

    def _resolve_session_id(self, session_id: str | None) -> str:
        """优先使用传入的会话 ID，并在持久化存储中补建缺失的会话。未指定 ID 时创建一个新会话 ID。"""
        if session_id:
            if self._session_manager is not None and not self._session_manager.exists(session_id):
                self._session_manager.store.create(session_id)
            return session_id

        if self._session_manager is not None:
            return self._session_manager.create()

        return str(uuid.uuid4())[:8]

    def set_session(self, session_id: str) -> None:
        """切换活跃会话，启用持久化时加载该会话的历史。"""
        if self._active_stream is not None or self._active_durable_segment:
            raise RuntimeError("Cannot switch sessions while generation is running")
        # 选择新的会话，并将同一个 ID 同步给底层 Agent。
        self.session_id = self._resolve_session_id(session_id)
        self.agent.reset_session(self.session_id)
        # 加载目标会话的历史。关闭持久化时从空列表开始。
        self.messages = (
            self._session_manager.load(self.session_id)
            if self._session_manager is not None
            else []
        )

    def create_session(self) -> str:
        """创建并切换到新会话，返回其 ID。流式生成或持久化运行期间禁止切换。"""
        if self._active_stream is not None or self._active_durable_segment:
            raise RuntimeError("Cannot switch sessions while generation is running")
        if self._session_manager is None:
            session_id = str(uuid.uuid4())[:8]
        else:
            session_id = self._session_manager.create()
        self.set_session(session_id)
        return session_id

    @staticmethod
    def _event_message_id(event: StreamEvent) -> str | None:
        """从流式事件读取非空的 message_id，无有效 ID 时返回 None。"""
        value = event.get("message_id")
        if isinstance(value, str) and value.strip():
            return value
        return None

    @staticmethod
    def _event_parent_user_message_id(event: StreamEvent) -> str | None:
        """从流式事件读取关联的用户消息 ID，无有效 ID 时返回 None。"""
        value = event.get("parent_user_message_id")
        if isinstance(value, str) and value.strip():
            return value
        return None

    def _persisted_ids_for_active_run(self) -> set[str]:
        """返回当前流式运行已经写入存储的消息 ID 集合。没有活跃流时返回空集合。"""
        return self._active_stream.persisted_message_ids if self._active_stream else set()

    def _save_streaming_runtime_state(
        self, state: _StreamPersistenceState, *, message_id: str, parent_user_message_id: str | None,
    ) -> None:
        """保存当前流的运行 ID 和助手消息 ID，以便结束或中断时定位这条消息。"""
        if self._session_manager is None:
            return
        payload: dict[str, Any] = {
            "version": 1,
            "state": "streaming",
            "run_id": state.run_id,
            "assistant_message_id": message_id,
        }
        if parent_user_message_id:
            payload["parent_user_message_id"] = parent_user_message_id
        self._session_manager.save_runtime_state(state.session_id, payload)

    def _persist_assistant_message(
        self,
        *,
        state: _StreamPersistenceState,
        message_id: str,
        parent_user_message_id: str | None,
        content: str,
        reasoning: str = "",
        usage: dict[str, int] | None = None,
        context_usage: dict[str, int] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        extra_fields: dict[str, Any] | None = None,
    ) -> None:
        """按消息 ID 持久化助手消息。

        同步更新当前流的正文和推理缓存。已写入的消息原地更新，首次写入时追加到历史。
        """
        if self._session_manager is None:
            return

        state.assistant_parent_ids[message_id] = parent_user_message_id
        state.assistant_contents[message_id] = content
        state.assistant_reasoning[message_id] = reasoning

        def build_message(base: dict[str, Any] | None = None) -> dict[str, Any]:
            """根据当前增量构造助手消息，必要时以已有记录作为更新基础。"""
            message: dict[str, Any] = {
                "role": "assistant",
                "message_id": message_id,
                "parent_user_message_id": parent_user_message_id,
                "content": content,
                "completion_state": "complete",
            }
            if base is not None:
                message.update(base)
                message["role"] = "assistant"
                message["message_id"] = message_id
                message["parent_user_message_id"] = parent_user_message_id
                message["content"] = content
                message["completion_state"] = "complete"
            if reasoning:
                message["reasoning"] = reasoning
            elif base is not None and "reasoning" in message:
                message.pop("reasoning", None)
            if usage:
                message["usage"] = dict(usage)
            if context_usage:
                message["context_usage"] = dict(context_usage)
            if tool_calls:
                normalized_tool_calls = normalize_tool_calls(tool_calls)
                if normalized_tool_calls:
                    message["tool_calls"] = normalized_tool_calls
            if extra_fields:
                message.update(extra_fields)
            return message

        if message_id in state.persisted_message_ids:
            self._session_manager.update_message(
                state.session_id,
                message_id,
                lambda current: build_message(dict(current)),
            )
            return

        self._session_manager.append_message(state.session_id, build_message())
        state.persisted_message_ids.add(message_id)

    def _persist_answer_message_for_question(
        self,
        *,
        question_id: str,
        state: _StreamPersistenceState,
    ) -> None:
        """从当前消息中找到指定问题的用户回答，只把尚未持久化的回答写入会话。"""
        if self._session_manager is None:
            return

        persisted_ids = self._persisted_ids_for_active_run()
        for message in reversed(self.messages):
            if message.get("role") != "user":
                continue
            if message.get("answer_to_question_id") != question_id:
                continue
            message_id = message.get("message_id")
            if not isinstance(message_id, str) or not message_id.strip():
                continue
            if message_id in persisted_ids:
                return
            self._session_manager.append_message(state.session_id, dict(message))
            state.persisted_message_ids.add(message_id)
            return

    def _update_in_memory_message(
        self,
        message_id: str,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any] | None:
        """按 ID 查找内存消息，把其副本交给 updater，再保存并返回更新结果。找不到时返回 None。"""
        for index, message in enumerate(self.messages):
            if message.get("message_id") != message_id:
                continue
            updated = updater(dict(message))
            # 将更新后的消息写回列表中的原位置。
            self.messages[index] = updated
            return updated
        return None

    async def _handle_stream_persistence_event(
        self,
        event: StreamEvent,
        state: _StreamPersistenceState,
    ) -> None:
        """根据流式事件保存助手消息、文本增量及提问状态。

        启用持久化执行时，普通消息由运行日志同步，这里只保存用于恢复的待回答问题。
        """
        if self._session_manager is None:
            return

        event_type = event.get("type")
        if self.agent.run_store is not None:
            if event_type == "ask_user_question":
                durable_run_id = (event.get("data") or {}).get("durable_run_id")
                self._session_manager.save_runtime_state(state.session_id, {
                    "version": 1,
                    "state": "awaiting_user_answer",
                    "durable_run_id": durable_run_id,
                    "assistant_message_id": event.get("message_id"),
                    "pending_question": {
                        key: event[key] for key in (
                            "message_id", "question_id", "prompt", "options", "allow_free_text", "required",
                        )
                    },
                })
            return
        message_id = self._event_message_id(event)
        parent_user_message_id = self._event_parent_user_message_id(event)
        if message_id is not None and message_id not in state.assistant_parent_ids:
            state.assistant_parent_ids[message_id] = parent_user_message_id

        if event_type == "assistant_start":
            if message_id is None:
                return
            self._persist_assistant_message(
                state=state,
                message_id=message_id,
                parent_user_message_id=state.assistant_parent_ids.get(message_id),
                content=state.assistant_contents.get(message_id, ""),
                reasoning=state.assistant_reasoning.get(message_id, ""),
            )
            self._save_streaming_runtime_state(
                state,
                message_id=message_id,
                parent_user_message_id=state.assistant_parent_ids.get(message_id),
            )
            return

        if event_type == "assistant_reasoning_delta":
            if message_id is None:
                return
            next_reasoning = state.assistant_reasoning.get(message_id, "") + str(event.get("reasoning_text") or "")
            self._persist_assistant_message(
                state=state,
                message_id=message_id,
                parent_user_message_id=state.assistant_parent_ids.get(message_id),
                content=state.assistant_contents.get(message_id, ""),
                reasoning=next_reasoning,
            )
            self._save_streaming_runtime_state(
                state,
                message_id=message_id,
                parent_user_message_id=state.assistant_parent_ids.get(message_id),
            )
            return

        if event_type == "assistant_delta":
            if message_id is None:
                return
            next_content = state.assistant_contents.get(message_id, "") + str(event.get("delta_text") or "")
            self._persist_assistant_message(
                state=state,
                message_id=message_id,
                parent_user_message_id=state.assistant_parent_ids.get(message_id),
                content=next_content,
                reasoning=state.assistant_reasoning.get(message_id, ""),
            )
            self._save_streaming_runtime_state(
                state,
                message_id=message_id,
                parent_user_message_id=state.assistant_parent_ids.get(message_id),
            )
            return

        if event_type == "assistant_end":
            if message_id is None:
                return
            content = str(event.get("content") or state.assistant_contents.get(message_id, ""))
            reasoning = str(event.get("reasoning") or state.assistant_reasoning.get(message_id, ""))
            usage = event.get("usage")
            tool_calls = event.get("tool_calls")
            self._persist_assistant_message(
                state=state,
                message_id=message_id,
                parent_user_message_id=state.assistant_parent_ids.get(message_id),
                content=content,
                reasoning=reasoning,
                usage=usage if isinstance(usage, dict) and usage else None,
                tool_calls=tool_calls if isinstance(tool_calls, list) and tool_calls else None,
            )
            if event.get("finish_reason") != "tool_calls":
                self._clear_streaming_state(state)
            return

        if event_type == "ask_user_question":
            if message_id is None:
                return
            question_id = str(event.get("question_id") or "").strip()
            prompt = str(event.get("prompt") or "")
            options = [dict(item) for item in event.get("options") or []]
            allow_free_text = bool(event.get("allow_free_text", True))
            required = bool(event.get("required", True))
            usage = event.get("usage")
            context_usage = event.get("context_usage")
            state.question_message_ids[question_id] = message_id
            self._persist_assistant_message(
                state=state,
                message_id=message_id,
                parent_user_message_id=state.assistant_parent_ids.get(message_id),
                content=state.assistant_contents.get(message_id) or prompt,
                reasoning=state.assistant_reasoning.get(message_id, ""),
                usage=usage if isinstance(usage, dict) and usage else None,
                context_usage=context_usage if isinstance(context_usage, dict) and context_usage else None,
                extra_fields={
                    "interaction_type": "askuserquestion",
                    "question_id": question_id,
                    "question_prompt": prompt,
                    "question_options": options,
                    "question_allow_free_text": allow_free_text,
                    "question_required": required,
                    "question_pending": True,
                },
            )
            self._session_manager.save_runtime_state(
                state.session_id,
                {
                    "version": 1,
                    "state": "awaiting_user_answer",
                    **({"trace_run_id": state.run_id} if self.config.trace_dir is not None else {}),
                    "assistant_message_id": message_id,
                    "pending_question": {
                        "question_id": question_id,
                        "message_id": message_id,
                        "prompt": prompt,
                        "options": options,
                        "allow_free_text": allow_free_text,
                        "required": required,
                    },
                },
            )
            return

        if event_type == "ask_user_answer_received":
            question_id = str(event.get("question_id") or "").strip()
            message_id = state.question_message_ids.get(question_id)
            if message_id:
                self._session_manager.update_message(
                    state.session_id,
                    message_id,
                    lambda current: {**current, "question_pending": False},
                )
            self._persist_answer_message_for_question(question_id=question_id, state=state)
            saved = self._session_manager.load_runtime_state(state.session_id)
            if (saved and saved.get("state") == "awaiting_user_answer"
                    and saved.get("assistant_message_id") == message_id):
                self._session_manager.delete_runtime_state(state.session_id, expected=saved)

    def _clear_streaming_state(self, state: _StreamPersistenceState, *, interrupted: bool = False) -> None:
        """清理与本次运行 ID 匹配的流式状态。发生中断时，先将对应的助手消息标为已中断。"""
        if self._session_manager is None:
            return
        saved = self._session_manager.load_runtime_state(state.session_id)
        if not saved or saved.get("state") != "streaming" or saved.get("run_id") != state.run_id:
            return
        if interrupted:
            message_id = saved.get("assistant_message_id")
            if isinstance(message_id, str) and message_id.strip():
                self._session_manager.update_message(
                    state.session_id, message_id,
                    lambda current: {**current, "completion_state": "interrupted"},
                )
        self._session_manager.delete_runtime_state(state.session_id, expected=saved)

    def _durable_store(self) -> RunStore:
        """获取 Agent 的持久化运行存储。功能未启用时抛出 DurableRunError。"""
        if self.agent.run_store is None:
            raise DurableRunError("Durable execution is disabled.")
        return self.agent.run_store

    def list_runs(self, *, incomplete_only: bool = False) -> list[RunState]:
        """列出当前会话在此工作区保存的 Agent 执行记录。

        记录按创建时间从新到旧排列。传入 incomplete_only=True 时，只返回尚未结束的运行。
        """
        return self._durable_store().list_runs(self.session_id, incomplete_only=incomplete_only)

    def list_run_steps(self, run_id: str) -> list[StepState]:
        """查看当前会话中指定运行已提交的有序日志。"""
        return self._durable_store().list_steps(self.session_id, run_id)

    def pause_run(self, run_id: str) -> bool:
        """请求在活跃运行的下一个安全边界暂停。"""
        return self._durable_store().pause(self.session_id, run_id)

    def list_child_runs(self, parent_run_id: str) -> list[ChildRun]:
        """查看当前父会话中指定运行的持久化子运行。"""
        return self._durable_store().list_children(self.session_id, parent_run_id)

    def _child_runtime(self, parent_run_id: str, child_run_id: str) -> tuple[DurableSubagents, ChildRun]:
        """验证子运行归属，返回处理该子运行的持久化执行器及运行记录。"""
        child = self._durable_store().get_child(self.session_id, parent_run_id, child_run_id)
        runtime = self.agent.durable_subagents
        if runtime is None:
            raise DurableRunError("Durable child execution is disabled.")
        return runtime, child

    def list_child_artifacts(self, parent_run_id: str, child_run_id: str) -> list[ChildArtifact]:
        """返回指定子运行已提交的交付清单。"""
        runtime, child = self._child_runtime(parent_run_id, child_run_id)
        return runtime.list_artifacts(child)

    def read_child_artifact(self, parent_run_id: str, child_run_id: str, path: str) -> str:
        """验证并读取子运行已提交的交付文件。"""
        runtime, child = self._child_runtime(parent_run_id, child_run_id)
        return runtime.read_artifact(child, path)

    def apply_child_artifact(
        self, parent_run_id: str, child_run_id: str, path: str, destination: str,
    ) -> bool:
        """在父工作区创建指定文件。目标字节已相同时返回 False。"""
        content = self.read_child_artifact(parent_run_id, child_run_id, path)
        [relative] = parse_deliverable_paths([destination])
        workdir = self.agent.workdir.resolve()
        try:
            require_outside_root(self._durable_store().root, workdir / relative, "Deliverable destination")
        except ValueError as exc:
            raise ArtifactError("A child deliverable cannot be applied to durable run storage.") from exc
        return apply_child_artifact(workdir, relative, content)

    def list_child_run_steps(self, parent_run_id: str, child_run_id: str) -> list[StepState]:
        """按顺序列出指定子运行的工具步骤及状态。"""
        store = self._durable_store()
        child = store.get_child(self.session_id, parent_run_id, child_run_id)
        return store.for_child(child).list_steps(child.run.session_id, child.run.run_id)

    def pause_child_run(self, parent_run_id: str, child_run_id: str) -> bool:
        """请求中断活跃的子运行并清理其资源。"""
        store = self._durable_store()
        child = store.get_child(self.session_id, parent_run_id, child_run_id)
        return store.for_child(child).pause(child.run.session_id, child.run.run_id)

    async def resolve_child_run_step(
        self, parent_run_id: str, child_run_id: str, step_id: str, output: str, *, is_error: bool = False,
    ) -> None:
        """确认 Docker 清理完成后，记录经过核实的工具结果。"""
        if not isinstance(output, str) or type(is_error) is not bool:
            raise ValueError("Recovery requires tool result text and a boolean error flag.")
        runtime, child = self._child_runtime(parent_run_id, child_run_id)
        await runtime.resolve(child, step_id, output, is_error=is_error)

    async def abandon_child_run(self, parent_run_id: str, child_run_id: str) -> None:
        """确认工作区和 Docker 清理状态后，关闭已停止的子运行。"""
        runtime, child = self._child_runtime(parent_run_id, child_run_id)
        await runtime.abandon(child)

    def resolve_run_step(self, run_id: str, step_id: str, output: str, *, is_error: bool = False) -> None:
        """记录结果不明步骤经核实的结果，避免再次调用工具。"""
        if not isinstance(output, str) or type(is_error) is not bool:
            raise ValueError("Recovery requires tool result text and a boolean error flag.")
        with self._durable_store().claim(self.session_id, run_id) as journal:
            journal.resolve(step_id, output, is_error=is_error)

    def abandon_run(self, run_id: str) -> None:
        """执行者退出后，关闭尚未完成的运行。"""
        with self._durable_store().claim(self.session_id, run_id) as journal:
            journal.abandon()
            if self._session_manager is not None:
                saved = self._session_manager.load_runtime_state(self.session_id)
                if saved and saved.get("durable_run_id") == journal.run_id:
                    message_id = saved.get("assistant_message_id")
                    if message_id:
                        self._session_manager.update_message(
                            self.session_id, message_id, lambda message: {**message, "question_pending": False},
                        )
                    self._session_manager.delete_runtime_state(self.session_id, expected=saved)

    async def resume_run(
        self,
        run_id: str,
        *,
        reasoning_effort: str | None = None,
    ) -> ChatResult:
        """按照当前工具策略恢复活跃会话中的持久化运行。"""
        self._durable_store()
        if self._active_stream is not None or self._active_durable_segment:
            raise RuntimeError("Generation is already running on this bot")
        prev_stream = self.agent.stream_enabled
        self.agent.set_stream_enabled(False)
        try:
            messages, usage = await self._run_durable_once(
                prompt=None, interrupt_queue=None, reasoning_effort=reasoning_effort, resume_run_id=run_id,
            )
        finally:
            self.agent.set_stream_enabled(prev_stream)
        return ChatResult(self.session_id, messages, _last_assistant_text(messages), usage)

    def resume_run_stream(
        self,
        run_id: str,
        *,
        reasoning_effort: str | None = None,
        stop_on_ask_user_question: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """继续持久化运行，逐个产出运行事件。"""
        self._durable_store()
        return self._stream_events(
            None, None, reasoning_effort, stop_on_ask_user_question, resume_run_id=run_id,
        )

    def _file_checkpoint_store(self) -> GitFileCheckpoints:
        """获取文件检查点存储。功能未启用时抛出 FileCheckpointError。"""
        if self.agent.file_checkpoints is None:
            raise FileCheckpointError("File checkpoints are disabled.")
        return self.agent.file_checkpoints

    async def list_file_checkpoints(self) -> list[FileCheckpoint]:
        """列出当前工作区和应用主目录保留的文件检查点。"""
        return await asyncio.to_thread(self._file_checkpoint_store().list)

    async def diff_file_checkpoint(self, checkpoint_id: str) -> str:
        """显示单个文件已记录的变更。"""
        store = self._file_checkpoint_store()
        return await asyncio.to_thread(store.diff, checkpoint_id)

    async def rollback_file_checkpoint(self, checkpoint_id: str) -> bool:
        """恢复仍匹配检查点的目标。检查点已使用时返回 False。"""
        store = self._file_checkpoint_store()
        return await finish_file_operation(lambda: store.rollback(checkpoint_id))

    def list_sessions(self) -> list[dict[str, Any]]:
        """返回持久化会话的元数据，包括路径、时间、消息数量和预览。未启用持久化时返回空列表。"""
        if self._session_manager is None:
            return []
        sessions = []
        for meta in self._session_manager.list_all():
            sessions.append(
                {
                    "session_id": meta.session_id,
                    "path": str(meta.path),
                    "created_at": meta.created_at.isoformat(),
                    "modified_at": meta.modified_at.isoformat(),
                    "message_count": meta.message_count,
                    "preview": meta.preview,
                }
            )
        return sessions

    def delete_session(self, session_id: str) -> bool:
        """删除指定的持久化会话并返回删除结果。删除当前会话后创建一个新会话。"""
        if self._session_manager is None:
            return False
        if self._active_stream is not None and self._active_stream.session_id == session_id:
            raise RuntimeError("Cannot delete a session while its stream is running")
        store = self.agent.run_store
        with store.guard_session_mutation(session_id) if store is not None else nullcontext():
            ok = self._session_manager.delete(session_id)
        if ok and session_id == self.session_id:
            self.create_session()
        return ok

    def register_tool(self, tool: ToolInput) -> None:
        """注册工具，接受 BaseTool、Python 函数或 ToolSpec 字典。"""
        if self.agent.restricted_workspace:
            raise ValueError("Custom Python tools are unavailable in a restricted Docker workspace")
        if isinstance(tool, BaseTool):
            self.agent.tool_registry.register(tool)
            return

        if callable(tool):
            from ..tools.function import FunctionTool

            self.agent.tool_registry.register(FunctionTool(tool))
            return

        if isinstance(tool, dict):
            func = tool.get("func")
            if not callable(func):
                raise TypeError("ToolSpec dict must include a callable 'func'")
            from ..tools.function import FunctionTool

            self.agent.tool_registry.register(
                FunctionTool(
                    func,
                    name=tool.get("name"),
                    description=tool.get("description"),
                    input_schema=tool.get("input_schema"),
                )
            )
            return

        raise TypeError(f"Unsupported tool type: {type(tool).__name__}")

    async def connect_mcp(self) -> dict[str, Exception | None]:
        """连接配置中的 MCP 服务并注册可用工具，返回以服务名为键的连接结果。"""
        return await self.agent.connect_mcp_servers()

    def cancel(self) -> None:
        """如果正在生成回复，尽力取消。"""
        q = self._active_interrupt_queue
        if q is not None:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._cancel_tool_approvals()
        pending = self._pending_question_future
        if pending is not None and not pending.done():
            pending.set_exception(UserInterruptedError("Interrupted while waiting for user answer"))
            return

        if self._active_stream is not None:
            self._clear_streaming_state(self._active_stream, interrupted=True)

    def _cancel_tool_approvals(self) -> None:
        """取消活跃流的审批，将仍在等待的审批结果设为 False 以唤醒调用方。"""
        if self._active_stream is not None:
            self._active_stream.approvals_cancelled = True
        for future in self._pending_tool_approvals.values():
            if not future.done():
                future.set_result(False)

    async def _wait_for_tool_approval(self, request: ToolApprovalRequest) -> bool:
        """优先使用调用方提供的审批处理器，否则在活跃流中发布审批事件并等待决定。

        返回布尔值表示是否通过。没有可用审批渠道或流已取消时返回 False。
        """
        state = self._active_stream
        if state is not None and state.approvals_cancelled:
            return False
        if self._tool_approval_handler is not None:
            approved = await self._tool_approval_handler(request)
            return approved is True and not (state is not None and state.approvals_cancelled)
        if state is None:
            return False
        future = asyncio.get_running_loop().create_future()
        # 先登记等待句柄，再发出审批事件，便于前端立即提交决定。
        self._pending_tool_approvals[request.approval_id] = future
        try:
            await self._event_router.emit({
                "type": "tool_approval_request",
                "session_id": state.session_id,
                "approval_id": request.approval_id,
                "tool_name": request.tool_name,
                "approval_actor": request.actor,
                "approval_preview": request.preview,
            })
            approved = await future
            return approved and not state.approvals_cancelled
        finally:
            # 审批结束或中断后移除等待句柄，避免旧 ID 被重复使用。
            self._pending_tool_approvals.pop(request.approval_id, None)

    def submit_tool_approval(self, approval_id: str, approved: bool) -> None:
        """处理一个活跃审批请求。ID 过期或已使用时抛出 ValueError。"""
        future = self._pending_tool_approvals.get(approval_id)
        if self._active_stream is None or self._active_stream.approvals_cancelled or future is None or future.done():
            raise ValueError("No live tool approval matches this ID")
        if type(approved) is not bool:
            raise ValueError("Tool approval decision must be boolean")
        future.set_result(approved)

    async def _wait_for_user_answer(self, question: dict[str, Any]) -> dict[str, Any]:
        """保存待回答的问题并等待提交答案。配置为遇到提问即暂停时，结束本次流以便稍后恢复。"""
        if self._active_stream is not None and self._active_stream.stop_on_ask_user_question:
            raise UserInterruptedError("Paused for user answer")
        if self._pending_question_future is not None and not self._pending_question_future.done():
            raise RuntimeError("Another askuserquestion interaction is already pending")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        # 保存可供调用方查询的问题副本。
        self._pending_question = dict(question)
        # 登记等待提交答案的异步结果。
        self._pending_question_future = future
        try:
            return await future
        finally:
            # 结束等待后清除问题，避免界面继续显示已处理的问题。
            self._pending_question = None
            # 清除已结束的等待句柄，为下一次提问让出状态。
            self._pending_question_future = None

    def pending_question(self) -> dict[str, Any] | None:
        """返回当前等待回答的问题副本。没有待回答问题时返回 None。"""
        if self._pending_question is None:
            return None
        return dict(self._pending_question)

    async def submit_user_answer(
        self,
        *,
        question_id: str,
        answer_text: str,
        selected_option_value: str | None = None,
    ) -> None:
        """向匹配的待回答问题提交文本和可选的选项值。问题 ID 不匹配或已处理时抛出 ValueError。"""
        pending = self._pending_question
        future = self._pending_question_future
        if pending is None or future is None:
            raise ValueError("No askuserquestion interaction is pending")
        if str(pending.get("question_id") or "") != str(question_id):
            raise ValueError("Pending question id does not match")
        if future.done():
            raise ValueError("Pending question is already resolved")
        future.set_result(
            {
                "answer_text": answer_text,
                "selected_option_value": selected_option_value,
            }
        )

    def stream_existing_messages(
        self,
        *,
        reasoning_effort: str | None = None,
        stop_on_ask_user_question: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """根据当前已保存的消息历史继续生成。"""
        return self._stream_events(None, None, reasoning_effort, stop_on_ask_user_question)

    async def resume_pending_question_stream(
        self,
        *,
        question_id: str,
        answer_text: str,
        selected_option_value: str | None = None,
        reasoning_effort: str | None = None,
        parent_run_id: str | None = None,
        durable_run_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """恢复处于等待提问回答状态的一轮执行，直到完成或再次暂停。"""
        durable_answer = {
            "question_id": question_id, "answer_text": answer_text,
            "selected_option_value": selected_option_value,
        } if durable_run_id is not None else None
        async for event in self._stream_events(
            None, None, reasoning_effort, True, parent_run_id=parent_run_id,
            resume_run_id=durable_run_id, durable_answer=durable_answer,
        ):
            yield event

    async def chat(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        reasoning_effort: str | None = None,
    ) -> ChatResult:
        """发起非流式聊天。按增量接收结果时使用 :meth:`stream`。"""
        if session_id is not None and session_id != self.session_id:
            self.set_session(session_id)

        if self._active_stream is not None or self._active_durable_segment:
            raise RuntimeError("Generation is already running on this bot")
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        await self._event_router.set_queue(queue)
        prev_stream = self.agent.stream_enabled
        self.agent.set_stream_enabled(False)

        try:
            result_messages, run_usage = await self._run_once(
                prompt,
                interrupt_queue=None,
                reasoning_effort=reasoning_effort,
            )
        finally:
            self.agent.set_stream_enabled(prev_stream)
            await self._event_router.set_queue(None)

        usage: dict[str, int] | None = run_usage
        drained: list[StreamEvent] = []
        while True:
            try:
                drained.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        for event in reversed(drained):
            if event.get("type") == "assistant_end":
                candidate = event.get("usage") or {}
                if candidate:
                    usage = dict(candidate)
                break

        assistant_text = _last_assistant_text(result_messages)
        return ChatResult(
            session_id=self.session_id,
            messages=result_messages,
            assistant_text=assistant_text,
            usage=usage,
        )

    def chat_sync(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        reasoning_effort: str | None = None,
    ) -> ChatResult:
        """在同步环境中执行一轮聊天并返回 ChatResult。已有事件循环时请使用 chat()。"""
        if _has_running_loop():
            raise RuntimeError("chat_sync() cannot be used inside a running event loop; use 'await chat()'.")
        return asyncio.run(self.chat(prompt, session_id=session_id, reasoning_effort=reasoning_effort))

    def stream(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        reasoning_effort: str | None = None,
        stop_on_ask_user_question: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """发起流式聊天，逐个返回结构化事件。"""
        return self._stream_events(prompt, session_id, reasoning_effort, stop_on_ask_user_question)

    async def _stream_events(
        self, prompt: str | None, session_id: str | None, reasoning_effort: str | None,
        stop_on_ask_user_question: bool,
        *,
        parent_run_id: str | None = None,
        resume_run_id: str | None = None,
        durable_answer: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """启动后台任务执行 Agent，并从事件队列逐条产出结构化事件。

        负责绑定会话、持久化回调和中断队列。异步消费者提前退出时移除事件订阅，生成任务仍可继续。
        """
        if session_id == "":
            if self._active_stream is not None:
                raise RuntimeError("A stream is already running on this bot")
            session_id = self._resolve_session_id(session_id)
        state = _StreamPersistenceState(
            session_id=self.session_id if session_id is None else session_id,
            stop_on_ask_user_question=stop_on_ask_user_question,
        )
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue(maxsize=256)
        interrupt_queue: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        detached = False

        async def produce() -> None:
            """持有会话的流式运行所有权，选择开始、继续或恢复运行，并在结束时清理状态。"""
            if self._active_stream is not None or self._active_durable_segment:
                raise RuntimeError("Generation is already running on this bot")
            with own_stream(self._session_manager, state.session_id, state.run_id):
                if state.session_id != self.session_id:
                    self.set_session(state.session_id)
                # 绑定新流的运行状态，供事件持久化和审批处理使用。
                self._active_stream = state
                # 暴露当前生成的中断队列，让 cancel() 可以通知本次流。
                self._active_interrupt_queue = interrupt_queue
                prev_stream = self.agent.stream_enabled
                try:
                    trace_parent_run_id = parent_run_id
                    if (self.agent.run_store is None and self.config.trace_dir is not None and prompt is None
                            and trace_parent_run_id is None and self._session_manager is not None):
                        saved = self._session_manager.load_runtime_state(state.session_id)
                        if saved and saved.get("state") == "awaiting_user_answer":
                            trace_parent_run_id = saved.get("trace_run_id")
                    await self._event_router.set_queue(None if detached else queue)
                    await self._event_router.set_tap(
                        lambda event: self._handle_stream_persistence_event(event, state)
                    )
                    self.agent.set_stream_enabled(True)
                    if self.agent.run_store is not None:
                        await self._run_durable_once(
                            prompt=prompt, interrupt_queue=interrupt_queue, reasoning_effort=reasoning_effort,
                            run_id=state.run_id, parent_run_id=parent_run_id,
                            resume_run_id=resume_run_id, durable_answer=durable_answer,
                        )
                    elif resume_run_id is not None:
                        raise DurableRunError("Durable execution is disabled.")
                    elif prompt is None:
                        await self._run_existing_messages_once(
                            interrupt_queue=interrupt_queue, reasoning_effort=reasoning_effort,
                            parent_run_id=trace_parent_run_id,
                        )
                    else:
                        await self._run_once(
                            prompt, interrupt_queue=interrupt_queue, reasoning_effort=reasoning_effort,
                        )
                except asyncio.CancelledError:
                    self._clear_streaming_state(state, interrupted=True)
                    raise
                except (UserInterruptedError, DurableRunPaused):
                    self._clear_streaming_state(state, interrupted=True)
                except Exception as exc:
                    await self._event_router.emit({
                        "type": "system", "message": "Error during generation.",
                        "data": {"error": str(exc)},
                    })
                    raise
                finally:
                    try:
                        self.agent.set_stream_enabled(prev_stream)
                        await self._event_router.set_tap(None)
                        if self._session_manager is not None:
                            # 流结束时重新加载落盘的会话历史，使内存与持久化结果一致。
                            self.messages = self._session_manager.load(state.session_id)
                    finally:
                        self._cancel_tool_approvals()
                        # 流结束后解除中断队列引用。
                        self._active_interrupt_queue = None
                        # 释放活跃流状态，允许后续生成或切换会话。
                        self._active_stream = None

        task = asyncio.create_task(produce(), name=f"minibot-stream-{state.session_id}")
        state.producer = task
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            while not task.done() or not queue.empty():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                yield event
            await task
        finally:
            detached = True
            if self._active_stream is state and self._tool_approval_handler is None:
                self._cancel_tool_approvals()
            self._event_router.detach_queue(queue)

    def stream_sync(
        self,
        prompt: str,
        *,
        session_id: str | None = None,
        reasoning_effort: str | None = None,
        stop_on_ask_user_question: bool = False,
    ) -> Iterator[StreamEvent]:
        """用独立事件循环把异步事件流包装成同步迭代器。关闭迭代器时清理生成任务与事件循环。"""
        if _has_running_loop():
            raise RuntimeError("stream_sync() cannot be used inside a running event loop; use 'async for e in stream()'.")
        loop = asyncio.new_event_loop()
        agen = self.stream(
            prompt,
            session_id=session_id,
            reasoning_effort=reasoning_effort,
            stop_on_ask_user_question=stop_on_ask_user_question,
        )
        try:
            while True:
                try:
                    event = loop.run_until_complete(agen.__anext__())
                except StopAsyncIteration:
                    break
                yield event
        finally:
            try:
                state = self._active_stream
                producer = state.producer if state is not None else None
                if producer is not None and producer.get_loop() is loop:
                    loop.run_until_complete(self._event_router.set_queue(None))
                    producer.cancel()
                    loop.run_until_complete(asyncio.gather(producer, return_exceptions=True))
                tasks = asyncio.all_tasks(loop)
                for task in tasks:
                    task.cancel()
                if tasks:
                    loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
                loop.run_until_complete(agen.aclose())
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()

    async def _run_existing_messages_once(
        self,
        *,
        interrupt_queue: "asyncio.Queue[None] | None",
        reasoning_effort: str | None,
        parent_run_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, int] | None]:
        """用现有消息执行一轮 Agent 循环，将尚未落盘的新消息写入会话，返回消息列表和用量。"""
        pre_len = len(self.messages)
        usage: dict[str, int] | None = None
        interrupted_error: UserInterruptedError | None = None
        parent_user_message_id = _last_user_message_id(self.messages)
        trace_options: dict[str, Any] = {}
        if self.config.trace_dir is not None:
            trace_options = {
                "run_id": self._active_stream.run_id if self._active_stream is not None else None,
                "parent_run_id": parent_run_id,
            }

        try:
            await self.agent.run_loop(
                self.messages,
                interrupt_queue=interrupt_queue,
                reasoning_effort=reasoning_effort,
                **trace_options,
            )
        except UserInterruptedError as exc:
            interrupted_error = exc
        except Exception as exc:
            if isinstance(exc, (RuntimeBudgetExceeded, ContextWindowExceeded)) and self._active_stream is not None:
                self._clear_streaming_state(self._active_stream)
            error_msg = {
                "role": "assistant",
                "content": f"[Error: {exc}]",
                "message_id": _new_message_id(),
                "parent_user_message_id": parent_user_message_id,
            }
            # 将执行异常作为助手错误消息保留，供调用方读到原因。
            self.messages.append(error_msg)

        new_messages = self.messages[pre_len:] if len(self.messages) >= pre_len else self.messages
        if self._session_manager is not None:
            persisted_ids = self._persisted_ids_for_active_run()
            for msg in new_messages:
                message_id = msg.get("message_id")
                if isinstance(message_id, str) and message_id in persisted_ids:
                    continue
                self._session_manager.append_message(self.session_id, msg)

        usage = _last_assistant_usage(new_messages) or _last_assistant_usage(self.messages)
        if interrupted_error is not None:
            raise interrupted_error
        return self.messages, usage

    async def _run_durable_once(
        self,
        *,
        prompt: str | None,
        interrupt_queue: "asyncio.Queue[None] | None",
        reasoning_effort: str | None,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        resume_run_id: str | None = None,
        durable_answer: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, int] | None]:
        """通过持久化运行日志开始或恢复一个执行片段，返回消息列表和用量。

        恢复运行时传入 resume_run_id，提交恢复所需的提问答案时传入 durable_answer。
        """
        if self._active_durable_segment:
            raise RuntimeError("Generation is already running on this bot")
        # 在进入持久化执行前标记为活跃，防止并发启动。
        self._active_durable_segment = True
        session_id = self.session_id
        working = list(self.messages)

        def seed() -> list[dict[str, Any]]:
            """加载会话的初始消息，并在提供 prompt 时添加本轮用户消息。"""
            messages = self._session_manager.load(session_id) if self._session_manager is not None else working[:]
            if prompt is not None:
                messages.append({"role": "user", "content": prompt, "message_id": _new_message_id()})
            return messages

        def publish(messages: list[dict[str, Any]]) -> None:
            """将运行日志中的消息同步到会话。有匹配答案时清除对应的待回答状态。"""
            if self._session_manager is None:
                # 没有会话存储时，在内存中接收运行日志发布的消息。
                self.messages = messages
                return
            self._session_manager.store.project_durable_messages(session_id, messages)
            saved = self._session_manager.load_runtime_state(session_id)
            if saved and saved.get("state") == "awaiting_user_answer":
                question = saved.get("pending_question") or {}
                if any(message.get("answer_to_question_id") == question.get("question_id") for message in messages
                       if message.get("answer_to_question_id")):
                    self._session_manager.delete_runtime_state(session_id, expected=saved)

        try:
            result = await self.agent.run_loop(
                working, interrupt_queue=interrupt_queue, reasoning_effort=reasoning_effort,
                run_id=run_id, parent_run_id=parent_run_id, resume_run_id=resume_run_id,
                durable_answer=durable_answer, seed_messages=seed, publish_messages=publish,
            )
            return result, _last_assistant_usage(result)
        finally:
            # 片段退出后总是清除活跃标记。
            self._active_durable_segment = False
            if self._session_manager is not None:
                # 片段退出后加载已投影到会话存储的消息。
                self.messages = self._session_manager.load(session_id)

    async def _run_once(
        self,
        prompt: str,
        *,
        interrupt_queue: "asyncio.Queue[None] | None",
        reasoning_effort: str | None,
    ) -> tuple[list[dict[str, Any]], dict[str, int] | None]:
        """处理一条新的用户输入。普通运行先保存用户消息再进入 Agent 循环，持久化运行交由日志管理。"""
        if self.agent.run_store is not None:
            return await self._run_durable_once(
                prompt=prompt, interrupt_queue=interrupt_queue, reasoning_effort=reasoning_effort,
            )
        user_msg = {"role": "user", "content": prompt, "message_id": _new_message_id()}
        # 将新一轮的用户消息加入当前上下文，再交给 Agent 执行。
        self.messages.append(user_msg)
        if self._session_manager is not None:
            self._session_manager.append_message(self.session_id, user_msg)
        return await self._run_existing_messages_once(
            interrupt_queue=interrupt_queue,
            reasoning_effort=reasoning_effort,
        )
