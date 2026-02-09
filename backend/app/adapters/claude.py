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

logger = logging.getLogger(__name__)


class ClaudeAdapter(ProviderAdapter):
    """Adapter for Claude models using OAuth via Claude Agent SDK (zero API cost).

    OAuth Setup:
        1. Install Claude Code CLI: npm install -g @anthropic-ai/claude-code
        2. Run `claude` once to authenticate via browser
        3. Credentials cached at ~/.claude/
    """

    # Model name mapping: full ID -> SDK short name
    MODEL_MAP: ClassVar[dict[str, str]] = {
        "claude-opus-4-5": "opus",
        "claude-sonnet-4-5": "sonnet",
        "claude-haiku-4-5": "haiku",
        "claude-opus-4-5-20250514": "opus",
        "claude-sonnet-4-5-20250514": "sonnet",
        "claude-haiku-4-5-20250514": "haiku",
        "opus": "opus",
        "sonnet": "sonnet",
        "haiku": "haiku",
    }

    def __init__(
        self,
        permission_callback: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None,
        after_tool_callback: (Callable[[str, dict[str, Any], str], Awaitable[None]] | None) = None,
    ):
        """
        Initialize Claude adapter (OAuth-only mode).

        Args:
            permission_callback: Async callback for tool permission prompts.
                Called with (tool_name, tool_args), returns True to allow.
            after_tool_callback: Async callback after tool execution.
                Called with (tool_name, tool_input, tool_output).
        """
        self._permission_callback = permission_callback
        self._after_tool_callback = after_tool_callback

        # Check for Claude CLI
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
        **kwargs: Any,
    ) -> CompletionResult:
        """
        Generate completion using Claude via OAuth.

        Args:
            messages: Conversation messages
            model: Model identifier
            temperature: Sampling temperature (unused in OAuth mode)
            **kwargs: Additional parameters

        Returns:
            CompletionResult
        """
        # Apply retry logic directly here
        from tenacity import (
            retry,
            retry_if_exception,
            stop_after_attempt,
            wait_random_exponential,
        )

        from app.adapters.base import is_retriable_error

        retry_decorator = retry(
            retry=retry_if_exception(is_retriable_error),
            stop=stop_after_attempt(3),
            wait=wait_random_exponential(multiplier=1, min=2, max=30),
            reraise=True,
        )

        async def _complete_with_retry() -> CompletionResult:
            assert self._cli_path is not None  # Guaranteed by __init__
            return await complete_oauth(
                messages=messages,
                model=model,
                cli_path=self._cli_path,
                model_map=self.MODEL_MAP,
                provider_name=self.provider_name,
                **kwargs,
            )

        _complete_with_retry_decorated = retry_decorator(_complete_with_retry)
        result: CompletionResult = await _complete_with_retry_decorated()
        return result

    async def health_check(self) -> bool:
        """Check if Claude is reachable (OAuth mode)."""
        # For OAuth, just check CLI exists
        return self._cli_path is not None

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """
        Stream completion from Claude via OAuth.
        """
        assert self._cli_path is not None  # Guaranteed by __init__
        async for event in stream_oauth(
            messages=messages,
            model=model,
            cli_path=self._cli_path,
            model_map=self.MODEL_MAP,
            **kwargs,
        ):
            yield event

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        write_enabled: bool = False,
        yolo_mode: bool = False,
        working_dir: str | None = None,
        resume_session_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        """Generate with native tool calling using PreToolUse/PostToolUse hooks.

        Args:
            messages: Conversation messages
            model: Model identifier
            tools: Tool definitions in Anthropic API format
            write_enabled: Whether write tools are enabled
            yolo_mode: Auto-approve all write tool requests
            working_dir: Working directory for agent
            resume_session_id: SDK session ID to resume (for continuation)
            **kwargs: Additional parameters

        Yields:
            Tuple of (SDK message object, session_id).
            session_id is populated from init and included with each yield.
        """
        from app.adapters.claude_tools import complete_with_tools as _complete_with_tools

        assert self._cli_path is not None  # Guaranteed by __init__
        async for message in _complete_with_tools(
            messages=messages,
            model=model,
            tools=tools,
            write_enabled=write_enabled,
            yolo_mode=yolo_mode,
            working_dir=working_dir,
            resume_session_id=resume_session_id,
            cli_path=self._cli_path,
            model_map=self.MODEL_MAP,
            provider_name=self.provider_name,
            permission_callback=self._permission_callback,
            after_tool_callback=self._after_tool_callback,
            **kwargs,
        ):
            yield message
