"""LLM 客户端封装。"""

import os
from typing import Any

from openai import AsyncOpenAI, OpenAI


class LLMClient:
    """封装 LLM API 客户端。"""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ):
        """用指定的端点、凭证和模型初始化同步与异步客户端。"""
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("MODEL_ID", "gpt-4.1-mini")

        self._sync_client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )
        self._async_client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )
        self._closed = False

    def _reasoning_kwargs(self, reasoning_effort: str | None) -> dict[str, Any]:
        """按服务商要求转换推理强度参数。"""
        effort = str(reasoning_effort or "").strip().lower()
        if effort not in {"low", "medium", "high"}:
            return {}
        base_url = str(self.base_url or "").lower()
        if "openrouter.ai" in base_url:
            return {"reasoning": {"effort": effort}}
        return {"reasoning_effort": effort}

    @staticmethod
    def _is_reasoning_effort_unsupported_error(exc: Exception) -> bool:
        """判断 API 异常是否表示服务端不接受推理强度参数。"""
        text = str(exc).lower()
        param_markers = (
            "reasoning_effort",
            "reasoning effort",
            "reasoning.effort",
            '"reasoning"',
            "'reasoning'",
        )
        unsupported_markers = (
            "unsupported",
            "unknown parameter",
            "unexpected",
            "unrecognized",
            "not permitted",
            "extra inputs",
            "invalid",
        )
        return any(marker in text for marker in param_markers) and any(
            marker in text for marker in unsupported_markers
        )

    def _build_kwargs(
        self,
        *,
        model: str,
        messages: list[dict],
        system: str,
        tools: list[dict] | None,
        max_tokens: int,
        stream: bool = False,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        """构建聊天补全请求的关键字参数。"""
        chat_messages = []
        if system:
            chat_messages.append({"role": "system", "content": system})

        outcome_fields = {"tool_status", "tool_exit_code", "tool_artifact_id", "tool_hook_error", "tool_hook_phase", "is_error"}
        chat_messages.extend(
            {key: value for key, value in message.items() if key not in outcome_fields}
            for message in messages
        )

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": chat_messages,
            "max_tokens": max_tokens,
        }
        kwargs.update(self._reasoning_kwargs(reasoning_effort))
        if tools:
            kwargs["tools"] = tools
        if stream:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}
        return kwargs

    def _create_sync_with_fallback(self, kwargs: dict[str, Any]) -> Any:
        """发起同步请求，在服务端明确不支持推理参数时省略该参数重试。"""
        try:
            return self._sync_client.chat.completions.create(**kwargs)
        except Exception as exc:
            if not any(key in kwargs for key in ("reasoning_effort", "reasoning")):
                raise
            if not self._is_reasoning_effort_unsupported_error(exc):
                raise
            fallback_kwargs = {
                key: value
                for key, value in kwargs.items()
                if key not in {"reasoning_effort", "reasoning"}
            }
            return self._sync_client.chat.completions.create(**fallback_kwargs)

    async def _create_async_with_fallback(self, kwargs: dict[str, Any]) -> Any:
        """发起异步请求，在服务端明确不支持推理参数时省略该参数重试。"""
        try:
            return await self._async_client.chat.completions.create(**kwargs)
        except Exception as exc:
            if not any(key in kwargs for key in ("reasoning_effort", "reasoning")):
                raise
            if not self._is_reasoning_effort_unsupported_error(exc):
                raise
            fallback_kwargs = {
                key: value
                for key, value in kwargs.items()
                if key not in {"reasoning_effort", "reasoning"}
            }
            return await self._async_client.chat.completions.create(**fallback_kwargs)

    def create_message(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict] | None = None,
        max_tokens: int = 8000,
        reasoning_effort: str | None = None,
    ) -> Any:
        """使用 LLM 创建消息，供已弃用的同步兼容路径使用。"""
        kwargs = self._build_kwargs(
            model=self.model,
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
        return self._create_sync_with_fallback(kwargs)

    async def create_message_async(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict] | None = None,
        max_tokens: int = 8000,
        reasoning_effort: str | None = None,
    ) -> Any:
        """通过异步 OpenAI 客户端创建消息。"""
        kwargs = self._build_kwargs(
            model=self.model,
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
        return await self._create_async_with_fallback(kwargs)

    async def create_message_stream_async(
        self,
        messages: list[dict],
        system: str,
        tools: list[dict] | None = None,
        max_tokens: int = 8000,
        reasoning_effort: str | None = None,
    ) -> Any:
        """通过异步 OpenAI 客户端创建流式响应。"""
        kwargs = self._build_kwargs(
            model=self.model,
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            stream=True,
            reasoning_effort=reasoning_effort,
        )
        return await self._create_async_with_fallback(kwargs)

    async def close(self) -> None:
        """关闭底层异步客户端占用的资源。"""
        if self._closed:
            return
        if hasattr(self._sync_client, "close"):
            self._sync_client.close()
        await self._async_client.close()
        self._closed = True
