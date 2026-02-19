"""Claude adapter with dual-mode: direct API (OAuth token) or CLI (Claude Agent SDK)."""

import json
import logging
import shutil
import time
from collections.abc import AsyncIterator, Awaitable, Callable
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
from app.adapters.claude_utils import build_permission_checker

logger = logging.getLogger(__name__)

AfterToolCB = Callable[[str, dict[str, Any], str, int | None], Awaitable[None]]


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

    def __init__(self, after_tool_callback: AfterToolCB | None = None, **kwargs: Any):
        """Initialize Claude adapter.

        Accepts if EITHER CLI or OAuth token is available.

        Args:
            after_tool_callback: Called with (tool_name, input, output, duration_ms).
            **kwargs: Ignored (for backward compatibility).
        """
        self._after_tool_callback = after_tool_callback
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
        """Whether to use direct Anthropic API (vs CLI)."""
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

    async def _complete_direct(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
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
                create_kwargs["system"] = system_text
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
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream using direct Anthropic API with OAuth token."""
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
                create_kwargs["system"] = system_text
            if temperature != 1.0:
                create_kwargs["temperature"] = temperature

            input_tokens = 0
            output_tokens = 0

            async with client.messages.stream(**create_kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                        yield StreamEvent(type="content", content=event.delta.text)

                final_message = await stream.get_final_message()
                input_tokens = final_message.usage.input_tokens
                output_tokens = final_message.usage.output_tokens

            yield StreamEvent(
                type="done",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason="end_turn",
            )
        except Exception as e:
            logger.error("Claude direct API stream error: %s", e)
            yield StreamEvent(type="error", error=str(e))
        finally:
            await client.close()

    @staticmethod
    def _convert_messages(messages: list[Message]) -> tuple[str, list[dict[str, str]]]:
        """Convert internal Message format to Anthropic API format.

        Returns (system_text, api_messages).
        """
        system_parts: list[str] = []
        api_messages: list[dict[str, str]] = []

        for msg in messages:
            if msg["role"] == "system":
                system_parts.append(msg["content"])
            else:
                api_messages.append({"role": msg["role"], "content": msg["content"]})

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
        """Stream completion from Claude via direct API or CLI."""
        if self._use_direct_api:
            async for event in self._stream_direct(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            ):
                yield event
            return

        # CLI path
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
        resume_session_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        """Generate with native tool calling. Yields (SDK message, session_id).

        Tool calling requires the CLI — direct API doesn't support agentic tool use.
        """
        from app.adapters.claude_tools import complete_with_tools as _complete_with_tools

        checker, yolo_mode = build_permission_checker(permission_config)
        assert self._cli_path is not None
        async for message in _complete_with_tools(
            messages=messages,
            model=model,
            tools=tools,
            yolo_mode=yolo_mode,
            permission_checker=checker,
            working_dir=working_dir,
            resume_session_id=resume_session_id,
            cli_path=self._cli_path,
            model_map=self.MODEL_MAP,
            provider_name=self.provider_name,
            after_tool_callback=self._after_tool_callback,
            **kwargs,
        ):
            yield message
