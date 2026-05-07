"""xAI direct adapter using OpenAI-compatible base."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.adapters._openai_compat_helpers import (
    handle_provider_error,
    is_auth_error,
    normalize_responses_content,
)
from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    Message,
    ProviderError,
    StreamEvent,
)
from app.adapters.errors import with_retry
from app.adapters.openai_compat import OpenAICompatibleAdapter

_XAI_CACHE_HEADER = "x-grok-conv-id"
_XAI_MULTI_AGENT_MODEL = "grok-4.20-multi-agent-0309"
_XAI_RESPONSES_API_MODELS = {_XAI_MULTI_AGENT_MODEL}
_XAI_MODEL_NORMALIZATION = {
    "grok-4.20": "grok-4.20-0309-reasoning",
    "grok-4.20-reasoning": "grok-4.20-0309-reasoning",
    "grok-4.20-beta-latest": "grok-4.20-0309-reasoning",
    "grok-4.20-beta-latest-non-reasoning": "grok-4.20-0309-reasoning",
    "grok-4.20-beta-0309-non-reasoning": "grok-4.20-0309-reasoning",
    "grok-4.20-multi-agent": _XAI_MULTI_AGENT_MODEL,
    "grok-4.20-multi-agent-beta-0309": _XAI_MULTI_AGENT_MODEL,
}


class XAIAdapter(OpenAICompatibleAdapter):
    """Adapter for xAI (Grok) models via direct API."""

    provider_prefix = "xai"

    @property
    def provider_name(self) -> str:
        return "xai"

    def _get_base_url(self) -> str:
        return "https://api.x.ai/v1"

    def _get_api_key(self, explicit_key: str | None) -> str:
        if not explicit_key:
            raise AuthenticationError("xai")
        return explicit_key

    def _resolve_model(self, model: str) -> str:
        """Normalize legacy Grok model IDs before sending them to xAI."""
        resolved = super()._resolve_model(model)
        return _XAI_MODEL_NORMALIZATION.get(resolved, resolved)

    @staticmethod
    def _uses_responses_api(model_id: str) -> bool:
        return model_id in _XAI_RESPONSES_API_MODELS

    @staticmethod
    def _extract_cache_headers(kwargs: dict[str, Any]) -> dict[str, str] | None:
        prompt_cache_key = kwargs.get("prompt_cache_key")
        if not prompt_cache_key:
            return None
        return {_XAI_CACHE_HEADER: str(prompt_cache_key)}

    @staticmethod
    def _merge_extra_headers(
        existing: dict[str, str] | None,
        extra: dict[str, str] | None,
    ) -> dict[str, str] | None:
        if not existing:
            return extra
        if not extra:
            return existing
        return {**existing, **extra}

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text:
            return output_text

        chunks: list[str] = []
        for item in getattr(response, "output", []) or []:
            for block in getattr(item, "content", []) or []:
                text = getattr(block, "text", None)
                if text:
                    chunks.append(str(text))
        return "".join(chunks)

    def _parse_responses_result(self, response: Any, model_id: str) -> CompletionResult:
        usage = getattr(response, "usage", None)
        output_details = getattr(usage, "output_tokens_details", None)
        reasoning_tokens = getattr(output_details, "reasoning_tokens", None)
        return CompletionResult(
            content=self._extract_response_text(response),
            model=getattr(response, "model", None) or model_id,
            provider=self.provider_name,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            finish_reason=getattr(response, "status", None) or "stop",
            raw_response=response,
            thinking_tokens=reasoning_tokens,
        )

    def _build_responses_params(
        self,
        *,
        model_id: str,
        messages: list[Message],
        temperature: float,
        max_tokens: int | None,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": model_id,
            "input": [
                {"role": msg.role, "content": normalize_responses_content(msg.role, msg.content)}
                for msg in messages
            ],
            "temperature": temperature,
        }
        if max_tokens:
            params["max_output_tokens"] = max_tokens
        # Live xAI verification on 2026-04-12 showed the endpoint rejects
        # reasoning effort for grok-4.20-multi-agent despite current docs.
        extra_headers = self._merge_extra_headers(
            kwargs.get("extra_headers"),
            self._extract_cache_headers(kwargs),
        )
        if extra_headers:
            params["extra_headers"] = extra_headers
        return params

    async def _complete_via_responses(
        self,
        *,
        messages: list[Message],
        model_id: str,
        max_tokens: int | None,
        temperature: float,
        kwargs: dict[str, Any],
    ) -> CompletionResult:
        if kwargs.get("tools"):
            raise ProviderError(
                "xAI multi-agent does not support Agent Hub client-side tool loops. "
                "Use plain completion mode or add explicit xAI Responses API built-in tool support.",
                provider=self.provider_name,
                retriable=False,
            )

        @with_retry
        async def _do_complete() -> CompletionResult:
            await self._refresh_credentials()
            params = self._build_responses_params(
                model_id=model_id,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                kwargs=kwargs,
            )
            try:
                response = await self._client.responses.create(**params)
                return self._parse_responses_result(response, model_id)
            except Exception as exc:
                if not is_auth_error(exc):
                    handle_provider_error(exc, self.provider_name)
                fresh = await self._refresh_credentials(allow_db_reload=True)
                if not fresh:
                    handle_provider_error(exc, self.provider_name)
                try:
                    response = await self._client.responses.create(**params)
                    return self._parse_responses_result(response, model_id)
                except Exception as second_exc:
                    handle_provider_error(second_exc, self.provider_name)
                    raise  # pragma: no cover

        return await _do_complete()

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        resolved_model = self._resolve_model(model)
        extra_headers = self._merge_extra_headers(
            kwargs.get("extra_headers"),
            self._extract_cache_headers(kwargs),
        )
        kwargs = {**kwargs, "extra_headers": extra_headers} if extra_headers else kwargs
        if self._uses_responses_api(resolved_model):
            return await self._complete_via_responses(
                messages=messages,
                model_id=resolved_model,
                max_tokens=max_tokens,
                temperature=temperature,
                kwargs=kwargs,
            )
        return await super().complete(
            messages=messages,
            model=resolved_model,
            max_tokens=max_tokens,
            temperature=temperature,
            cache_retention=cache_retention,
            **kwargs,
        )

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        resolved_model = self._resolve_model(model)
        extra_headers = self._merge_extra_headers(
            kwargs.get("extra_headers"),
            self._extract_cache_headers(kwargs),
        )
        kwargs = {**kwargs, "extra_headers": extra_headers} if extra_headers else kwargs
        if self._uses_responses_api(resolved_model):
            result = await self.complete(
                messages=messages,
                model=resolved_model,
                max_tokens=max_tokens,
                temperature=temperature,
                cache_retention=cache_retention,
                **kwargs,
            )
            if result.content:
                yield StreamEvent(type="content", content=result.content)
            yield StreamEvent(
                type="done",
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                finish_reason=result.finish_reason,
                thinking_tokens=result.thinking_tokens,
            )
            return
        async for event in super().stream(
            messages=messages,
            model=resolved_model,
            max_tokens=max_tokens,
            temperature=temperature,
            cache_retention=cache_retention,
            **kwargs,
        ):
            yield event

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        tool_handler: Any,
        max_turns: int = 20,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        resolved_model = self._resolve_model(model)
        if self._uses_responses_api(resolved_model):
            yield StreamEvent(
                type="error",
                error=(
                    "xAI multi-agent only supports xAI server-side tools via Responses API; "
                    "Agent Hub client-side tool execution is unavailable for this model."
                ),
            )
            return
        extra_headers = self._merge_extra_headers(
            kwargs.get("extra_headers"),
            self._extract_cache_headers(kwargs),
        )
        kwargs = {**kwargs, "extra_headers": extra_headers} if extra_headers else kwargs
        async for event in super().complete_with_tools(
            messages=messages,
            model=resolved_model,
            tools=tools,
            tool_handler=tool_handler,
            max_turns=max_turns,
            **kwargs,
        ):
            yield event
