"""负责注册和触发钩子的管理器。"""

from pathlib import Path
from typing import Any

from ..config.schema import HooksConfig, HookDefinition
from .events import HookEvent, HookContext, HookResult
from .executor import HookExecutor


class HookManager:
    """管理钩子的注册与执行。"""

    def __init__(self, config: HooksConfig, workdir: Path):
        """根据配置建立钩子执行器，并按事件整理已配置的钩子。"""
        self.config = config
        self.workdir = workdir
        self.enabled = config.enabled
        self.executor = HookExecutor(workdir)

        # 按事件组织钩子。
        self._hooks: dict[HookEvent, list[HookDefinition]] = {}
        for hook in config.hooks:
            if hook.enabled:
                event = HookEvent(hook.event)
                if event not in self._hooks:
                    self._hooks[event] = []
                self._hooks[event].append(hook)

    def get_hooks(self, event: HookEvent) -> list[HookDefinition]:
        """获取某个事件对应的所有钩子。"""
        return self._hooks.get(event, [])

    async def trigger(
        self,
        event: HookEvent,
        context: HookContext,
    ) -> list[HookResult]:
        """触发某个事件对应的所有钩子。"""
        if not self.enabled:
            return []

        hooks = self.get_hooks(event)
        if not hooks:
            return []

        results = []
        for hook in hooks:
            result = await self.executor.execute(
                handler=hook.handler,
                context=context,
                timeout=hook.timeout,
            )
            results.append(result)

            # 任一钩子阻止操作时，停止继续处理。
            if result.blocked:
                break

        return results

    async def trigger_pre_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """触发工具调用前的钩子，返回 (blocked, reason)。"""
        from .events import ToolCallContext

        context = ToolCallContext(
            event=HookEvent.PRE_TOOL_CALL,
            workdir=str(self.workdir),
            tool_name=tool_name,
            tool_args=tool_args,
        )

        results = await self.trigger(HookEvent.PRE_TOOL_CALL, context)

        for result in results:
            if result.blocked:
                return True, result.block_reason
            if not result.success:
                raise RuntimeError(result.error or "Pre-tool hook failed")

        return False, None

    async def trigger_post_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: str,
    ) -> None:
        """触发工具调用后的钩子。"""
        from .events import ToolCallContext

        context = ToolCallContext(
            event=HookEvent.POST_TOOL_CALL,
            workdir=str(self.workdir),
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=tool_result,
        )

        results = await self.trigger(HookEvent.POST_TOOL_CALL, context)
        for result in results:
            if not result.success or result.blocked:
                raise RuntimeError(result.error or result.block_reason or "Post-tool hook failed")

    async def trigger_session_start(self, session_id: str = "") -> list[HookResult]:
        """触发会话启动钩子。"""
        from .events import SessionContext

        context = SessionContext(
            event=HookEvent.SESSION_START,
            workdir=str(self.workdir),
            session_id=session_id,
        )

        return await self.trigger(HookEvent.SESSION_START, context)

    async def trigger_session_end(self, session_id: str = "") -> list[HookResult]:
        """触发会话结束钩子。"""
        from .events import SessionContext

        context = SessionContext(
            event=HookEvent.SESSION_END,
            workdir=str(self.workdir),
            session_id=session_id,
        )

        return await self.trigger(HookEvent.SESSION_END, context)

    async def trigger_teammate_idle(
        self,
        *,
        member_id: str,
        detail: str = "",
    ) -> list[HookResult]:
        """触发队友进入空闲状态时的钩子。"""
        from .events import TeamEventContext

        context = TeamEventContext(
            event=HookEvent.TEAMMATE_IDLE,
            workdir=str(self.workdir),
            team_member_id=member_id,
            detail=detail,
        )
        return await self.trigger(HookEvent.TEAMMATE_IDLE, context)

    async def trigger_task_completed(
        self,
        *,
        task_id: str,
        detail: str = "",
    ) -> list[HookResult]:
        """触发任务完成钩子。"""
        from .events import TeamEventContext

        context = TeamEventContext(
            event=HookEvent.TASK_COMPLETED,
            workdir=str(self.workdir),
            task_id=task_id,
            detail=detail,
        )
        return await self.trigger(HookEvent.TASK_COMPLETED, context)
