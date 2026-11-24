"""单个执行片段中模型和工具调用共享的限制。"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from ..config.schema import RuntimeBudgetConfig
from .model_context import estimate_payload_tokens, estimate_text_tokens


class RuntimeBudgetExceeded(RuntimeError):
    """运行达到配置的一项限制时抛出。"""

    def __init__(self, limit: str):
        """记录触发停止的运行预算限制名称。"""
        self.limit = limit
        super().__init__(f"budget_exceeded: {limit}")


@dataclass(frozen=True)
class ModelAllowance:
    input_estimate: int
    max_tokens: int


def _reported_tokens(usage: Any, field: str) -> int | None:
    """从用量结构中提取有效的 token 计数。"""
    reported = usage.get(field) if isinstance(usage, dict) else getattr(usage, field, None)
    return reported if type(reported) is int and reported >= 0 else None


class RuntimeBudget:
    """在当前事件循环中维护计数器和截止时间。"""

    def __init__(self, limits: RuntimeBudgetConfig):
        """按配置初始化计数器、预留额度和当前事件循环的截止时间。"""
        self.limits = limits
        self.loop = asyncio.get_running_loop()
        self.deadline = self.loop.time() + limits.max_wall_time
        self.llm_calls = 0
        self.tool_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._reserved_output_tokens = 0
        self._output_released = asyncio.Event()

    def _check_time(self) -> None:
        """检查当前执行片段是否超出时间预算。"""
        if self.loop.time() >= self.deadline:
            raise RuntimeBudgetExceeded("max_wall_time")

    @asynccontextmanager
    async def time_limit(self):
        """限制作用域内的异步操作耗时，并将超时转换为预算异常。"""
        self._check_time()
        timer = asyncio.timeout_at(self.deadline)
        try:
            async with timer:
                yield
        except TimeoutError as exc:
            if not timer.expired():
                raise
            raise RuntimeBudgetExceeded("max_wall_time") from exc

    @contextmanager
    def pause(self):
        """临时暂停时间预算，在退出作用域后补回等待时间。"""
        started = self.loop.time()
        try:
            yield
        finally:
            self.deadline += self.loop.time() - started

    def output_headroom(self, requested: int) -> int:
        """计算当前请求可用的输出 token 上限。"""
        remaining = self.limits.max_output_tokens - self.output_tokens - self._reserved_output_tokens
        if remaining <= 0:
            raise RuntimeBudgetExceeded("max_output_tokens")
        return min(requested, remaining)

    async def wait_for_output(self) -> None:
        """等待并发模型请求归还输出额度，或在预算不足时停止。"""
        while self.output_tokens < self.limits.max_output_tokens <= self.output_tokens + self._reserved_output_tokens:
            self._output_released.clear()
            async with self.time_limit():
                await self._output_released.wait()

    @contextmanager
    def reserve_output(self, allowance: ModelAllowance):
        """预留未使用的输出额度，直到并发模型请求结束。"""
        self._reserved_output_tokens += allowance.max_tokens
        try:
            yield
        finally:
            self._reserved_output_tokens -= allowance.max_tokens
            self._output_released.set()

    def start_model(self, *, input_estimate: int, max_tokens: int) -> ModelAllowance:
        """检查模型调用、输入预算和输出额度，并为本次请求计入尝试。"""
        self._check_time()
        if self.llm_calls >= self.limits.max_llm_calls:
            raise RuntimeBudgetExceeded("max_llm_calls")
        remaining_input = self.limits.max_input_tokens - self.input_tokens
        if remaining_input < input_estimate:
            raise RuntimeBudgetExceeded("max_input_tokens")
        output_tokens = self.output_headroom(max_tokens)
        self.llm_calls += 1
        self.input_tokens += input_estimate
        return ModelAllowance(input_estimate, output_tokens)

    def finish_model(
        self,
        allowance: ModelAllowance,
        usage: Any,
        output: tuple[str, str | None, list[Any]],
    ) -> None:
        """根据服务商实际用量或内容估算更新本次调用的预算统计。"""
        prompt_tokens = _reported_tokens(usage, "prompt_tokens")
        completion_tokens = _reported_tokens(usage, "completion_tokens")
        if prompt_tokens is not None:
            self.input_tokens += prompt_tokens - allowance.input_estimate
        if completion_tokens is None:
            text, reasoning, tool_calls = output
            # 兼容服务商可能通过两个提取路径返回相同文本。
            distinct_reasoning = reasoning if reasoning and reasoning != text else ""
            completion_tokens = estimate_text_tokens(text + distinct_reasoning)
            if tool_calls:
                completion_tokens += estimate_payload_tokens(tool_calls)
        self.output_tokens += completion_tokens
        if self.input_tokens > self.limits.max_input_tokens:
            raise RuntimeBudgetExceeded("max_input_tokens")
        if self.output_tokens > self.limits.max_output_tokens:
            raise RuntimeBudgetExceeded("max_output_tokens")

    def start_tool(self) -> None:
        """检查工具调用次数上限，并为即将执行的调用计数。"""
        self._check_time()
        if self.tool_calls >= self.limits.max_tool_calls:
            raise RuntimeBudgetExceeded("max_tool_calls")
        self.tool_calls += 1


current_budget: ContextVar[RuntimeBudget | None] = ContextVar("runtime_budget", default=None)
