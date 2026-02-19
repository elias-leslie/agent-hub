"""Claude adapter with OAuth via Claude SDK (zero API cost)."""

import logging
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, ClassVar

from app.adapters.base import (
    CompletionResult,
    Message,
    ProviderAdapter,
    StreamEvent,
)
from app.adapters.claude_oauth import complete_oauth
from app.adapters.claude_streaming import stream_oauth
from app.adapters.claude_utils import build_permission_checker

logger = logging.getLogger(__name__)

AfterToolCB = Callable[[str, dict[str, Any], str, int | None], Awaitable[None]]


class ClaudeAdapter(ProviderAdapter):
    """Adapter for Claude models using OAuth via Claude Agent SDK (zero API cost).

    OAuth Setup:
        1. Install Claude Code CLI: npm install -g @anthropic-ai/claude-code
        2. Run `claude` once to authenticate via browser
        3. Credentials cached at ~/.claude/
    """

    # Model name mapping: full ID -> SDK short name
    MODEL_MAP: ClassVar[dict[str, str]] = {
        "claude-opus-4-6": "opus",
        "claude-sonnet-4-5": "sonnet",
        "claude-haiku-4-5": "haiku",
        "claude-opus-4-5": "opus",  # Legacy alias
        "claude-opus-4-5-20250514": "opus",
        "claude-sonnet-4-5-20250514": "sonnet",
        "claude-haiku-4-5-20250514": "haiku",
        "opus": "opus",
        "sonnet": "sonnet",
        "haiku": "haiku",
    }

    def __init__(self, after_tool_callback: AfterToolCB | None = None, **kwargs: Any):
        """Initialize Claude adapter (OAuth-only mode).

        Args:
            after_tool_callback: Called with (tool_name, input, output, duration_ms).
            **kwargs: Ignored (for backward compatibility).
        """
        self._after_tool_callback = after_tool_callback
        self._cli_path = shutil.which("claude")
        if not self._cli_path:
            raise ValueError(
                "Claude adapter requires Claude CLI (OAuth mode only). "
                "Install CLI: npm install -g @anthropic-ai/claude-code"
            )
        logger.info(f"Claude adapter: OAuth mode (CLI: {self._cli_path})")

    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def auth_mode(self) -> str:
        """Return current authentication mode."""
        return "oauth"

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate completion using Claude via OAuth."""
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
        """Check if Claude is reachable (OAuth mode)."""
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
        """Stream completion from Claude via OAuth."""
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
        """Generate with native tool calling. Yields (SDK message, session_id)."""
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
