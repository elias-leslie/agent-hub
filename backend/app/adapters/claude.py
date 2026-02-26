"""Claude adapter with dual-mode: direct API (OAuth token) or CLI (Claude Agent SDK)."""

import json
import logging
import shutil
import time
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from app.adapters.base import (
    CompletionResult,
    Message,
    ProviderAdapter,
    ProviderError,
    StreamEvent,
)
from app.adapters.claude_oauth import complete_oauth
from app.adapters.claude_streaming import stream_oauth

logger = logging.getLogger(__name__)


class ClaudeAdapter(ProviderAdapter):
    """Adapter for Claude models with dual authentication modes.

    1. **Direct API** — Uses an OAuth token stored in the credential manager
       with the ``anthropic`` SDK's ``auth_token`` parameter.
    2. **CLI** — Falls back to the Claude Agent SDK which shells out to the
       ``claude`` CLI binary (zero API cost via Max subscription).

    Either mode (or both) can be available. Direct API is preferred when an
    OAuth token exists.
    """

    # Model name mapping: full ID -> SDK short name (for CLI mode)
    MODEL_MAP: ClassVar[dict[str, str]] = {
        "claude-opus-4-6": "opus",
        "claude-sonnet-4-6": "sonnet",
        "claude-haiku-4-5": "haiku",
        "opus": "opus",
        "sonnet": "sonnet",
        "haiku": "haiku",
    }

    # Full model IDs for the direct API
    API_MODEL_MAP: ClassVar[dict[str, str]] = {
        "opus": "claude-opus-4-6-20250219",
        "sonnet": "claude-sonnet-4-6-20250514",
        "haiku": "claude-haiku-4-5-20251001",
        "claude-opus-4-6": "claude-opus-4-6-20250219",
        "claude-sonnet-4-6": "claude-sonnet-4-6-20250514",
        "claude-haiku-4-5": "claude-haiku-4-5-20251001",
    }

    def __init__(self, **kwargs: Any):
        """Initialize Claude adapter.

        Accepts if EITHER CLI or OAuth token is available.

        Args:
            **kwargs: Ignored (for backward compatibility).
        """
        self._cli_path = shutil.which("claude")

        # Check for OAuth token in credential manager
        from app.services.credential_manager import get_credential_manager
        cm = get_credential_manager()
        self._has_oauth_token = cm.get("claude", "oauth_token") is not None

        if not self._cli_path and not self._has_oauth_token:
            raise ValueError(
                "Claude adapter requires either an OAuth token (via browser auth) "
                "or the Claude CLI. Install CLI: npm install -g @anthropic-ai/claude-code"
            )

        mode = []
        if self._has_oauth_token:
            mode.append("direct API")
        if self._cli_path:
            mode.append(f"CLI ({self._cli_path})")
        logger.info("Claude adapter: %s", " + ".join(mode))

    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def _use_direct_api(self) -> bool:
        """Whether to use direct Anthropic API (vs CLI).

        Prefer CLI when available — it uses the Claude Agent SDK which handles
        auth via the Max subscription. Direct API is only used as a fallback
        when CLI is not installed.
        """
        if self._cli_path:
            return False
        from app.services.credential_manager import get_credential_manager
        return get_credential_manager().get("claude", "oauth_token") is not None

    @property
    def auth_mode(self) -> str:
        """Return current authentication mode."""
        return "direct_api" if self._use_direct_api else "cli"

    async def _ensure_valid_token(self) -> str:
        """Get a valid OAuth access token, refreshing if needed.

        Returns the access token string.
        """
        from app.services.credential_manager import get_credential_manager
        cm = get_credential_manager()

        token_json = cm.get("claude", "oauth_token")
        if not token_json:
            raise ProviderError("No Claude OAuth token available", provider="claude", retriable=False)

        try:
            data = json.loads(token_json)
        except (json.JSONDecodeError, TypeError):
            # Treat as raw token
            return token_json

        access_token = data.get("access_token")
        expires_at = data.get("expires_at")

        # Check if expired (with 60s buffer)
        if expires_at and time.time() >= (expires_at - 60):
            refresh_token = cm.get("claude", "refresh_token")
            if not refresh_token:
                raise ProviderError(
                    "Claude OAuth token expired and no refresh token available",
                    provider="claude", retriable=False,
                )

            from app.adapters.claude_auth import refresh_claude_token
            logger.info("Refreshing expired Claude OAuth token")
            new_creds = await refresh_claude_token(refresh_token)

            # Update credential manager cache
            new_data = json.dumps({
                "access_token": new_creds.access_token,
                "expires_at": new_creds.expires_at,
            })
            cm.set("claude", "oauth_token", new_data)
            if new_creds.refresh_token:
                cm.set("claude", "refresh_token", new_creds.refresh_token)

            return new_creds.access_token

        if not access_token:
            raise ProviderError("Claude OAuth token data missing access_token", provider="claude", retriable=False)
        return access_token

    @staticmethod
    def _apply_cache_control(
        system_text: str, cache_retention: str
    ) -> str | list[dict[str, Any]]:
        """Wrap system text with cache_control if retention is requested.

        Returns a plain string (no caching) or a list-of-blocks with
        ``cache_control`` set (for prompt caching).
        """
        if cache_retention == "none" or not system_text:
            return system_text
        ttl = "1h" if cache_retention == "long" else "5m"
        return [
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral", "ttl": ttl},
            }
        ]

    async def _complete_direct(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        """Complete using direct Anthropic API with OAuth token."""
        import anthropic

        start_time = time.time()
        token = await self._ensure_valid_token()
        api_model = self.API_MODEL_MAP.get(model, model)

        # Convert messages to Anthropic format
        system_text, api_messages = self._convert_messages(messages)

        client = anthropic.AsyncAnthropic(auth_token=token)
        try:
            create_kwargs: dict[str, Any] = {
                "model": api_model,
                "messages": api_messages,
                "max_tokens": max_tokens or 4096,
            }
            if system_text:
                create_kwargs["system"] = self._apply_cache_control(system_text, cache_retention)
            if temperature != 1.0:
                create_kwargs["temperature"] = temperature

            response = await client.messages.create(**create_kwargs)

            content = ""
            for block in response.content:
                if block.type == "text":
                    content += block.text

            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "Claude direct API: %dms, model=%s, tokens=%d/%d",
                duration_ms, api_model, input_tokens, output_tokens,
            )

            return CompletionResult(
                content=content,
                model=api_model,
                provider=self.provider_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=response.stop_reason or "end_turn",
                raw_response=None,
            )
        finally:
            await client.close()

    async def _stream_direct(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream using direct Anthropic API with OAuth token.

        Supports tool definitions — when tools are present, the model may
        produce tool_use content blocks.  These are emitted as tool_use
        StreamEvents after text streaming completes, with the finish_reason
        set to ``"tool_use"`` so the caller can execute tools and re-stream.
        """
        import anthropic

        token = await self._ensure_valid_token()
        api_model = self.API_MODEL_MAP.get(model, model)

        system_text, api_messages = self._convert_messages(messages)

        client = anthropic.AsyncAnthropic(auth_token=token)
        try:
            create_kwargs: dict[str, Any] = {
                "model": api_model,
                "messages": api_messages,
                "max_tokens": max_tokens or 4096,
            }
            if system_text:
                create_kwargs["system"] = self._apply_cache_control(system_text, cache_retention)
            if temperature != 1.0:
                create_kwargs["temperature"] = temperature

            # Pass tool definitions to the API if provided
            tools = kwargs.get("tools")
            if tools:
                create_kwargs["tools"] = tools

            # Thinking support
            from app.adapters.claude_utils import get_claude_thinking_config

            thinking_level = kwargs.get("thinking_level")
            if thinking_level:
                thinking_config = get_claude_thinking_config(thinking_level)
                if thinking_config:
                    create_kwargs["thinking"] = thinking_config
                    # Anthropic requires max_tokens >= 1024 when thinking is enabled
                    create_kwargs["max_tokens"] = max(create_kwargs["max_tokens"], 1024)

            import asyncio

            abort_event: asyncio.Event | None = kwargs.get("abort_event")
            input_tokens = 0
            output_tokens = 0

            async with client.messages.stream(**create_kwargs) as stream:
                async for event in stream:
                    if abort_event is not None and abort_event.is_set():
                        raise asyncio.CancelledError("Abort signal received")
                    if event.type == "content_block_delta" and hasattr(event, "delta"):
                        if hasattr(event.delta, "text"):
                            yield StreamEvent(type="content", content=event.delta.text)
                        elif hasattr(event.delta, "thinking"):
                            yield StreamEvent(type="thinking", content=event.delta.thinking)

                final_message = await stream.get_final_message()
                input_tokens = final_message.usage.input_tokens
                output_tokens = final_message.usage.output_tokens

            # Emit tool_use events for any tool calls in the response
            finish_reason = final_message.stop_reason or "end_turn"
            for block in final_message.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    yield StreamEvent(
                        type="tool_use",
                        tool_id=block.id,  # type: ignore[union-attr]
                        tool_name=block.name,  # type: ignore[union-attr]
                        tool_input=block.input if isinstance(block.input, dict) else {},  # type: ignore[union-attr]
                    )

            yield StreamEvent(
                type="done",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
            )
        except Exception as e:
            logger.error("Claude direct API stream error: %s", e)
            yield StreamEvent(type="error", error=str(e))
        finally:
            await client.close()

    # Anthropic API valid fields per content block type.
    # Extra fields (tool_name, thought_signature) added by the shared streaming
    # layer for other providers must be stripped before sending to Anthropic.
    _VALID_BLOCK_FIELDS: ClassVar[dict[str, set[str]]] = {
        "text": {"type", "text"},
        "tool_use": {"type", "id", "name", "input"},
        "tool_result": {"type", "tool_use_id", "content", "is_error"},
        "image": {"type", "source"},
    }

    @classmethod
    def _sanitize_content(cls, content: str | list[dict[str, Any]]) -> str | list[dict[str, Any]]:
        """Strip non-Anthropic fields from content blocks.

        The shared streaming tool loop adds extra fields (``tool_name`` on
        tool_result, ``thought_signature`` on tool_use) for other providers.
        The Anthropic API rejects unknown fields, so they must be removed.
        """
        if isinstance(content, str):
            return content
        sanitized: list[dict[str, Any]] = []
        for block in content:
            block_type = block.get("type", "")
            allowed = cls._VALID_BLOCK_FIELDS.get(block_type)
            if allowed:
                sanitized.append({k: v for k, v in block.items() if k in allowed})
            else:
                # Unknown block type — pass through unchanged
                sanitized.append(block)
        return sanitized

    @classmethod
    def _convert_messages(cls, messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
        """Convert internal Message format to Anthropic API format.

        Returns (system_text, api_messages).
        """
        system_parts: list[str] = []
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content if isinstance(msg.content, str) else "")
            else:
                api_messages.append({
                    "role": msg.role,
                    "content": cls._sanitize_content(msg.content),
                })

        return "\n\n".join(system_parts), api_messages

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate completion using Claude via direct API or CLI."""
        if self._use_direct_api:
            return await self._complete_direct(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                cache_retention=cache_retention,
                **kwargs,
            )

        # CLI path
        from app.adapters.errors import with_retry

        @with_retry
        async def _do_complete() -> CompletionResult:
            assert self._cli_path is not None
            return await complete_oauth(
                messages=messages,
                model=model,
                cli_path=self._cli_path,
                model_map=self.MODEL_MAP,
                provider_name=self.provider_name,
                cache_retention=cache_retention,
                **kwargs,
            )

        return await _do_complete()

    async def health_check(self) -> bool:
        """Check if Claude is reachable (either mode)."""
        if self._use_direct_api:
            try:
                await self._ensure_valid_token()
                return True
            except Exception:
                pass
        return self._cli_path is not None

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream completion from Claude.

        When tools are present or CLI is unavailable, uses the direct Anthropic
        API. Otherwise falls back to the CLI path (Max subscription via Claude
        Agent SDK). The streaming tool loop handles tool execution for the
        direct API path.
        """
        if kwargs.get("tools") or self._use_direct_api:
            async for event in self._stream_direct(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                cache_retention=cache_retention,
                **kwargs,
            ):
                yield event
            return

        # CLI path (primary — uses Max subscription via Claude Agent SDK)
        assert self._cli_path is not None
        async for event in stream_oauth(
            messages=messages,
            model=model,
            cli_path=self._cli_path,
            model_map=self.MODEL_MAP,
            cache_retention=cache_retention,
            **kwargs,
        ):
            yield event

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        permission_config: dict[str, Any] | None = None,
        working_dir: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        """Generate with tool calling via direct Anthropic API.

        Yields (ToolEvent, session_id) pairs — same interface as Gemini's
        execute_tool_loop(). Tools are executed in-process via DirectToolHandler.
        """
        import traceback
        import uuid

        import anthropic

        from app.adapters.claude_utils import get_claude_thinking_config
        from app.adapters.gemini_events import ToolContentBlock, ToolEvent, ToolMessage
        from app.services.tools.base import ToolCall
        from app.services.tools.direct_executor import create_direct_handler

        token = await self._ensure_valid_token()
        handler = create_direct_handler(
            working_dir=working_dir,
            permission_config=permission_config,
            project_id=kwargs.get("project_id"),
        )
        api_model = self.API_MODEL_MAP.get(model, model)
        system_text, api_messages = self._convert_messages(messages)
        session_id = str(uuid.uuid4())

        # Convert tool defs to Anthropic format
        api_tools = [
            {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
            for t in tools
        ]

        max_turns = kwargs.get("max_turns", 15)
        accumulated_text = ""
        client = anthropic.AsyncAnthropic(auth_token=token)

        try:
            for _ in range(max_turns):
                create_kwargs: dict[str, Any] = {
                    "model": api_model,
                    "messages": api_messages,
                    "tools": api_tools,
                    "max_tokens": kwargs.get("max_tokens") or 4096,
                }
                if system_text:
                    create_kwargs["system"] = system_text
                thinking_level = kwargs.get("thinking_level")
                if thinking_level:
                    thinking_config = get_claude_thinking_config(thinking_level)
                    if thinking_config:
                        create_kwargs["thinking"] = thinking_config
                        create_kwargs["max_tokens"] = max(create_kwargs["max_tokens"], 1024)

                response = await client.messages.create(**create_kwargs)

                # Build ToolEvent blocks from response
                text_content = ""
                tool_calls: list[ToolCall] = []
                thinking_text = ""

                for block in response.content:
                    if hasattr(block, "type"):
                        if block.type == "text":
                            text_content += block.text
                        elif block.type == "thinking":
                            thinking_text += getattr(block, "thinking", "")
                        elif block.type == "tool_use":
                            tool_calls.append(ToolCall(
                                id=block.id,
                                name=block.name,
                                input=block.input if isinstance(block.input, dict) else {},
                            ))

                # Yield thinking event
                if thinking_text:
                    yield (
                        ToolEvent(
                            type="assistant",
                            message=ToolMessage(content=[
                                ToolContentBlock(type="thinking", text=thinking_text),
                            ]),
                        ),
                        session_id,
                    )

                # Yield text event
                if text_content:
                    accumulated_text += text_content
                    yield (
                        ToolEvent(
                            type="assistant",
                            message=ToolMessage(content=[
                                ToolContentBlock(type="text", text=text_content),
                            ]),
                        ),
                        session_id,
                    )

                # Yield tool_use events
                for tc in tool_calls:
                    yield (
                        ToolEvent(
                            type="assistant",
                            message=ToolMessage(content=[
                                ToolContentBlock(type="tool_use", name=tc.name, input=tc.input, id=tc.id),
                            ]),
                        ),
                        session_id,
                    )

                # No tool calls → final result
                if not tool_calls:
                    yield (ToolEvent(type="result", subtype="success", result=accumulated_text), session_id)
                    return

                # Execute tools and yield results
                tool_result_blocks: list[dict[str, Any]] = []
                for tc in tool_calls:
                    result = await handler.execute(tc)
                    yield (
                        ToolEvent(
                            type="tool_result",
                            content=result.content,
                            tool_use_id=tc.id,
                            is_error=result.is_error,
                            duration_ms=result.duration_ms,
                        ),
                        session_id,
                    )
                    block: dict[str, Any] = {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result.content,
                    }
                    if result.is_error:
                        block["is_error"] = True
                    tool_result_blocks.append(block)

                # Append assistant + tool results for next turn
                assistant_content: list[dict[str, Any]] = []
                for block in response.content:
                    if hasattr(block, "type"):
                        if block.type == "text":
                            assistant_content.append({"type": "text", "text": block.text})
                        elif block.type == "tool_use":
                            assistant_content.append({
                                "type": "tool_use", "id": block.id,
                                "name": block.name, "input": block.input,
                            })
                api_messages.append({"role": "assistant", "content": assistant_content})
                api_messages.append({"role": "user", "content": tool_result_blocks})

            # Max turns reached
            yield (ToolEvent(type="result", subtype="success", result=accumulated_text), session_id)

        except Exception as e:
            logger.error("Claude tool error: %s\n%s", e, traceback.format_exc())
            yield (ToolEvent(type="error", error=str(e)), session_id)
            raise ProviderError(f"Claude tool error: {e}", provider=self.provider_name, retriable=True) from e
        finally:
            await client.close()
