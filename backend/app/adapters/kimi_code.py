"""Kimi Code subscription adapter using Anthropic-compatible API."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import anthropic

from app.adapters._openai_compat_helpers import (
    load_credentials_from_db,
    resolve_api_key,
)
from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    Message,
    ProviderAdapter,
    ProviderError,
    StreamEvent,
)
from app.adapters.claude_direct import (
    _build_create_kwargs,
    _stream_events,
    convert_messages,
)
from app.adapters.tool_result_payload import normalize_tool_handler_result
from app.constants.agent_limits import DEFAULT_AGENTIC_MAX_TURNS
from app.constants.catalog_entries import get_max_output_tokens

logger = logging.getLogger(__name__)

KIMI_CODE_BASE_URL = "https://api.kimi.com/coding/"
KIMI_CODE_USER_AGENT = "agent-hub/1.0"
_EMPTY_FINAL_RESPONSE_MSG = (
    "You have finished tool work but have not produced a final user-facing response. "
    "Write the final response now. Do not call more tools unless a missing fact blocks the response."
)


class KimiCodeAdapter(ProviderAdapter):
    """Adapter for Kimi Code membership API.

    This is separate from the Moonshot pay-as-you-go adapter. Kimi Code uses
    a subscription API key, a coding-specific endpoint, and the stable model
    id ``kimi-for-coding``.
    """

    provider_prefix = "kimi-code"

    def __init__(self, api_key: str | None = None) -> None:
        self._explicit_api_key = api_key
        self._last_resolved_key = self._get_api_key(resolve_api_key(self.provider_name, api_key))

    @property
    def provider_name(self) -> str:
        return "kimi-code"

    def _get_base_url(self) -> str:
        return KIMI_CODE_BASE_URL

    def _get_default_headers(self) -> dict[str, str]:
        # Kimi requires coding clients to preserve their real identity.
        return {"User-Agent": KIMI_CODE_USER_AGENT}

    def _get_api_key(self, candidate: str | None) -> str:
        if not candidate:
            raise AuthenticationError("kimi-code")
        return candidate

    def _resolve_model(self, model: str) -> str:
        if model.startswith(f"{self.provider_prefix}/"):
            return model[len(self.provider_prefix) + 1 :]
        return model

    async def _refresh_credentials(self, *, allow_db_reload: bool = False) -> str:
        key = resolve_api_key(self.provider_name, self._explicit_api_key)
        if not key and allow_db_reload:
            key = await load_credentials_from_db(self.provider_name)
        self._last_resolved_key = self._get_api_key(key or self._last_resolved_key)
        return self._last_resolved_key

    def _build_client(self) -> Any:
        return anthropic.AsyncAnthropic(
            api_key=self._last_resolved_key,
            base_url=self._get_base_url(),
            default_headers=self._get_default_headers(),
        )

    @staticmethod
    def _raise_provider_error(error: Exception) -> None:
        message = str(error)
        lower = message.lower()
        if "401" in message or "authentication" in lower or "invalid" in lower:
            raise ProviderError(message, "kimi-code", retriable=False, status_code=401) from error
        if "403" in message or "access_terminated" in lower:
            raise ProviderError(message, "kimi-code", retriable=False, status_code=403) from error
        if "429" in message or "rate limit" in lower:
            raise ProviderError(message, "kimi-code", retriable=True, status_code=429) from error
        raise ProviderError(message, "kimi-code", retriable=True) from error

    async def health_check(self) -> bool:
        try:
            await self._refresh_credentials(allow_db_reload=True)
            return True
        except Exception:
            return False

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        from app.adapters.errors import with_retry

        @with_retry
        async def _do_complete() -> CompletionResult:
            start_time = time.time()
            await self._refresh_credentials()
            system_text, api_messages = convert_messages(messages)
            create_kwargs = _build_create_kwargs(
                self._resolve_model(model),
                api_messages,
                system_text,
                max_tokens or get_max_output_tokens(model),
                temperature,
                cache_retention,
            )
            client = self._build_client()
            try:
                async with client.messages.stream(**create_kwargs) as stream:
                    response = await stream.get_final_message()
            except Exception as e:
                logger.error("Kimi Code completion error: %s", e)
                self._raise_provider_error(e)
                raise
            finally:
                await client.close()

            content = _response_text(response)
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                "Kimi Code API: %dms, model=%s, tokens=%d/%d",
                duration_ms,
                response.model,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )
            return CompletionResult(
                content=content,
                model=response.model,
                provider=self.provider_name,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                finish_reason=response.stop_reason or "end_turn",
                raw_response=response,
            )

        return await _do_complete()

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        await self._refresh_credentials()
        system_text, api_messages = convert_messages(messages)
        create_kwargs = _build_create_kwargs(
            self._resolve_model(model),
            api_messages,
            system_text,
            max_tokens or get_max_output_tokens(model),
            temperature,
            cache_retention,
        )
        if tools := kwargs.get("tools"):
            create_kwargs["tools"] = [_to_anthropic_tool(tool) for tool in tools]
        abort_event = kwargs.get("abort_event")
        client = self._build_client()
        try:
            async for event in _stream_events(client, create_kwargs, abort_event):
                yield event
        except Exception as e:
            logger.error("Kimi Code stream error: %s", e)
            yield StreamEvent(type="error", error=str(e))
        finally:
            await client.close()

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        tool_handler: Callable[[str, dict[str, Any]], Awaitable[str]],
        max_turns: int = DEFAULT_AGENTIC_MAX_TURNS,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        await self._refresh_credentials()
        system_text, api_messages = convert_messages(messages)
        api_model = self._resolve_model(model)
        temperature = float(kwargs.get("temperature", 1.0))
        max_tokens = kwargs.get("max_tokens")
        resolved_max_tokens = max_tokens or get_max_output_tokens(model)
        empty_closeout_used = False
        client = self._build_client()
        try:
            for turn in range(max_turns):
                create_kwargs = _build_create_kwargs(
                    api_model,
                    api_messages,
                    system_text,
                    resolved_max_tokens,
                    temperature,
                    "none",
                )
                create_kwargs["tools"] = [_to_anthropic_tool(tool) for tool in tools]
                try:
                    async with client.messages.stream(**create_kwargs) as stream:
                        response = await stream.get_final_message()
                except Exception as e:
                    logger.error("Kimi Code complete_with_tools error: %s", e)
                    yield StreamEvent(type="error", error=str(e))
                    return

                response_blocks = [_content_block_to_dict(block) for block in response.content]
                text = _response_text(response)
                tool_blocks = [block for block in response_blocks if block.get("type") == "tool_use"]
                if tool_blocks:
                    if text:
                        yield StreamEvent(type="content", content=text)
                    api_messages.append({"role": "assistant", "content": response_blocks})
                    tool_result_blocks = []
                    for block in tool_blocks:
                        tool_id = str(block.get("id") or "")
                        tool_name = str(block.get("name") or "")
                        tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                        yield StreamEvent(
                            type="tool_use",
                            tool_id=tool_id,
                            tool_name=tool_name,
                            tool_input=tool_input,
                        )
                        tool_result = normalize_tool_handler_result(
                            await tool_handler(tool_name, tool_input)
                        )
                        yield StreamEvent(
                            type="tool_result",
                            tool_id=tool_id,
                            content=tool_result.content,
                            is_error=tool_result.is_error,
                            duration_ms=tool_result.duration_ms,
                        )
                        result_block = {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": tool_result.content,
                        }
                        if tool_result.is_error:
                            result_block["is_error"] = True
                        tool_result_blocks.append(result_block)
                    api_messages.append({"role": "user", "content": tool_result_blocks})
                    continue

                if not text.strip() and not empty_closeout_used and turn + 1 < max_turns:
                    api_messages.append({"role": "user", "content": _EMPTY_FINAL_RESPONSE_MSG})
                    empty_closeout_used = True
                    continue

                if text:
                    yield StreamEvent(type="content", content=text)
                yield StreamEvent(
                    type="done",
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    finish_reason=response.stop_reason or "end_turn",
                )
                return
            yield StreamEvent(type="done", finish_reason="max_turns")
        finally:
            await client.close()

    def complete_with_tool_events(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        working_dir: str | None,
        max_turns: int,
        project_id: str | None,
        session_id: str,
        agent_slug: str | None,
        tool_catalog: list[dict[str, Any]] | None,
    ) -> AsyncIterator[tuple[Any, str]]:
        from app.adapters.openai_tool_events import adapt_openai_stream

        return adapt_openai_stream(
            self,
            messages,
            model,
            tools,
            working_dir,
            max_turns,
            project_id,
            session_id,
            agent_slug=agent_slug,
            tool_catalog=tool_catalog,
        )


def _response_text(response: Any) -> str:
    return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")


def _content_block_to_dict(block: Any) -> dict[str, Any]:
    block_type = getattr(block, "type", None)
    if block_type == "text":
        return {"type": "text", "text": getattr(block, "text", "")}
    if block_type == "tool_use":
        tool_input = getattr(block, "input", {})
        return {
            "type": "tool_use",
            "id": getattr(block, "id", ""),
            "name": getattr(block, "name", ""),
            "input": tool_input if isinstance(tool_input, dict) else {},
        }
    return {"type": str(block_type or "text"), "text": str(block)}


def _to_anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
        function = tool["function"]
        return {
            "name": function["name"],
            "description": function.get("description", ""),
            "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
        }
    return {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "input_schema": tool.get("input_schema") or tool.get("parameters") or {"type": "object", "properties": {}},
    }
