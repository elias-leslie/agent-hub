"""Claude adapter with dual-mode: direct API (OAuth token) or CLI (Claude Agent SDK)."""

import logging
import shutil
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from app.adapters.base import (
    CompletionResult,
    Message,
    ProviderAdapter,
    StreamEvent,
)
from app.adapters.claude_direct import (
    complete_direct,
    convert_messages,
    sanitize_content,
    stream_direct,
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

    # Anthropic API valid fields per content block type (kept for back-compat).
    _VALID_BLOCK_FIELDS: ClassVar[dict[str, set[str]]] = {
        "text": {"type", "text"},
        "tool_use": {"type", "id", "name", "input"},
        "tool_result": {"type", "tool_use_id", "content", "is_error"},
        "image": {"type", "source"},
    }

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Claude adapter.

        Accepts if EITHER CLI or OAuth token is available.

        Args:
            **kwargs: Ignored (for backward compatibility).
        """
        self._cli_path = shutil.which("claude")

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

    @classmethod
    def _sanitize_content(
        cls, content: str | list[dict[str, Any]]
    ) -> str | list[dict[str, Any]]:
        """Strip non-Anthropic fields from content blocks (delegates to claude_direct)."""
        return sanitize_content(content)

    @classmethod
    def _convert_messages(
        cls, messages: list[Message]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Convert internal Message format to Anthropic API format (delegates to claude_direct)."""
        return convert_messages(messages)

    async def health_check(self) -> bool:
        """Check if Claude is reachable (either mode)."""
        if self._use_direct_api:
            try:
                from app.adapters.claude_direct import ensure_valid_token

                await ensure_valid_token()
                return True
            except Exception:
                pass
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
        if self._use_direct_api:
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
        return await self._complete_cli(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            cache_retention=cache_retention,
            **kwargs,
        )

    async def _complete_cli(
        self,
        messages: list[Message],
        model: str,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        """Complete using the Claude CLI via Agent SDK."""
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
        if self._use_direct_api:
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

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        permission_config: dict[str, Any] | None = None,
        working_dir: str | None = None,
        resume_session_id: str | None = None,
        max_turns: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        """Generate with native tool calling. Yields (SDK message, session_id).

        Tool calling requires the CLI — direct API doesn't support agentic tool use
        with Max subscription OAuth tokens.
        """
        from app.adapters.claude_tools_helpers import complete_with_tools as _complete_with_tools
        from app.adapters.claude_utils import build_permission_checker

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
            max_turns=max_turns,
            **kwargs,
        ):
            yield message
