"""Claude adapter with dual-mode: direct API (OAuth token) or CLI (Claude Agent SDK)."""

import logging
import shutil
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from app.adapters._claude_tool_session import ClaudeToolSessionMixin
from app.adapters.base import (
    CompletionResult,
    Message,
    ProviderAdapter,
    StreamEvent,
)
from app.adapters.claude_direct import (
    complete_direct,
    convert_messages,
    stream_direct,
)
from app.adapters.claude_oauth import complete_oauth
from app.adapters.claude_streaming import stream_oauth
from app.constants.models import CLAUDE_HAIKU, CLAUDE_OPUS, CLAUDE_OPUS_4_7, CLAUDE_SONNET

logger = logging.getLogger(__name__)


def _messages_have_image_content(messages: list[Message]) -> bool:
    return any(message.has_images() for message in messages)


class ClaudeAdapter(ClaudeToolSessionMixin, ProviderAdapter):
    """Adapter for Claude models with dual authentication modes.

    Supports Direct API (OAuth token via ``anthropic`` SDK) and CLI
    (Claude Agent SDK shelling out to the ``claude`` binary).  Direct API
    is preferred when an OAuth token exists; CLI is used otherwise.
    """

    # Model name mapping: full ID -> SDK short name (for CLI mode)
    MODEL_MAP: ClassVar[dict[str, str]] = {
        CLAUDE_OPUS: "opus",
        CLAUDE_OPUS_4_7: "opus",
        CLAUDE_SONNET: "sonnet",
        CLAUDE_HAIKU: "haiku",
        "opus": "opus",
        "sonnet": "sonnet",
        "haiku": "haiku",
    }

    # Full model IDs for the direct API (dated versions for API key auth)
    API_MODEL_MAP: ClassVar[dict[str, str]] = {
        "opus": f"{CLAUDE_OPUS}-20250219",
        "sonnet": f"{CLAUDE_SONNET}-20250514",
        "haiku": f"{CLAUDE_HAIKU}-20251001",
        CLAUDE_OPUS: f"{CLAUDE_OPUS}-20250219",
        CLAUDE_OPUS_4_7: CLAUDE_OPUS_4_7,
        CLAUDE_SONNET: f"{CLAUDE_SONNET}-20250514",
        CLAUDE_HAIKU: f"{CLAUDE_HAIKU}-20251001",
    }

    # Anthropic API valid fields per content block type (kept for back-compat).
    _VALID_BLOCK_FIELDS: ClassVar[dict[str, set[str]]] = {
        "text": {"type", "text"},
        "tool_use": {"type", "id", "name", "input"},
        "tool_result": {"type", "tool_use_id", "content", "is_error"},
        "image": {"type", "source"},
    }

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Claude adapter (accepts any of CLI, OAuth token, or API key)."""
        self._cli_path = shutil.which("claude")

        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        self._has_oauth_token = cm.get("claude", "oauth_token") is not None
        self._has_api_key = cm.get_api_key("claude") is not None

        if not self._cli_path and not self._has_oauth_token and not self._has_api_key:
            raise ValueError(
                "Claude adapter requires an OAuth token, API key, or the Claude CLI. "
                "Install CLI: npm install -g @anthropic-ai/claude-code"
            )

        mode = []
        if self._has_oauth_token:
            mode.append("direct API (OAuth)")
        if self._has_api_key:
            mode.append("direct API (API key)")
        if self._cli_path:
            mode.append(f"CLI ({self._cli_path})")
        logger.info("Claude adapter: %s", " + ".join(mode))

    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def _use_direct_api(self) -> bool:
        """True when CLI is absent but OAuth token or API key is present."""
        if self._cli_path:
            return False
        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        return cm.get("claude", "oauth_token") is not None or cm.get_api_key("claude") is not None

    def _should_use_direct_api(self, messages: list[Message]) -> bool:
        """Use direct API for multimodal requests; CLI prompt transport is text-only."""
        return self._use_direct_api or (
            _messages_have_image_content(messages)
            and (self._has_oauth_token or self._has_api_key)
        )

    @property
    def auth_mode(self) -> str:
        """Return current authentication mode."""
        return "direct_api" if self._use_direct_api else "cli"

    @classmethod
    def _convert_messages(
        cls, messages: list[Message]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Convert internal Message format to Anthropic API format (delegates to claude_direct)."""
        return convert_messages(messages)

    async def health_check(self) -> bool:
        """Check if Claude is reachable (any mode)."""
        if self._use_direct_api:
            try:
                from app.adapters.claude_direct import resolve_direct_credentials

                await resolve_direct_credentials()
                return True
            except Exception:
                logger.debug("Claude direct API credential validation failed", exc_info=True)
        return self._cli_path is not None

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
        if self._should_use_direct_api(messages):
            return await complete_direct(
                messages=messages,
                model=model,
                api_model_map=self.API_MODEL_MAP,
                provider_name=self.provider_name,
                max_tokens=max_tokens,
                temperature=temperature,
                cache_retention=cache_retention,
                **kwargs,
            )

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

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream completion from Claude via CLI (Agent SDK) or direct API."""
        if self._should_use_direct_api(messages):
            async for event in stream_direct(
                messages=messages,
                model=model,
                api_model_map=self.API_MODEL_MAP,
                max_tokens=max_tokens,
                temperature=temperature,
                cache_retention=cache_retention,
                **kwargs,
            ):
                yield event
            return

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
