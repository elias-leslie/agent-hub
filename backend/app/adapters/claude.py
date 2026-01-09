"""Claude adapter with OAuth via Claude SDK (zero API cost) and API key fallback."""

import logging
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal

import anthropic

from app.adapters.base import (
    AuthenticationError,
    CacheMetrics,
    CompletionResult,
    ContainerState,
    Message,
    ProviderAdapter,
    ProviderError,
    RateLimitError,
    StreamEvent,
    ToolCallResult,
)
from app.config import settings

logger = logging.getLogger(__name__)

# Cache TTL types supported by Anthropic
CacheTTL = Literal["ephemeral", "1h"]

# Tool categories for permission handling
READ_TOOLS = {"read_file", "search_code", "list_files", "get_project_structure"}
WRITE_TOOLS = {"write_file", "edit_file", "delete_file", "create_directory"}


class ClaudeAdapter(ProviderAdapter):
    """Adapter for Claude models.

    Primary: OAuth via Claude Agent SDK (zero API cost)
    Fallback: Anthropic API with API key

    OAuth Setup:
        1. Install Claude Code CLI: npm install -g @anthropic-ai/claude-code
        2. Run `claude` once to authenticate via browser
        3. Credentials cached at ~/.claude/

    API Key Setup:
        Set ANTHROPIC_API_KEY environment variable
    """

    # Model name mapping: full ID -> SDK short name
    MODEL_MAP: dict[str, str] = {
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
        api_key: str | None = None,
        prefer_oauth: bool = True,
        permission_callback: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None,
        after_tool_callback: (Callable[[str, dict[str, Any], str], Awaitable[None]] | None) = None,
    ):
        """
        Initialize Claude adapter.

        Args:
            api_key: Anthropic API key. Falls back to settings if not provided.
            prefer_oauth: If True, prefer OAuth via Claude SDK when available.
            permission_callback: Async callback for tool permission prompts.
                Called with (tool_name, tool_args), returns True to allow.
            after_tool_callback: Async callback after tool execution.
                Called with (tool_name, tool_input, tool_output).
        """
        self._api_key = api_key or settings.anthropic_api_key
        self._prefer_oauth = prefer_oauth
        self._permission_callback = permission_callback
        self._after_tool_callback = after_tool_callback

        # Check for Claude CLI
        self._cli_path = shutil.which("claude")
        self._use_oauth = self._prefer_oauth and self._cli_path is not None

        if self._use_oauth:
            logger.info(f"Claude adapter: OAuth mode (CLI: {self._cli_path})")
        elif self._api_key:
            logger.info("Claude adapter: API key mode")
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        else:
            raise ValueError(
                "Claude adapter requires either Claude CLI (OAuth) or API key. "
                "Install CLI: npm install -g @anthropic-ai/claude-code, or "
                "set ANTHROPIC_API_KEY environment variable."
            )

    @property
    def provider_name(self) -> str:
        return "claude"

    @property
    def auth_mode(self) -> str:
        """Return current authentication mode."""
        return "oauth" if self._use_oauth else "api_key"

    def _prepare_messages_with_cache(
        self,
        messages: list[dict[str, Any]],
        enable_caching: bool,
        cache_ttl: CacheTTL,
    ) -> list[dict[str, Any]]:
        """
        Prepare messages with cache breakpoints.

        Adds cache_control to the last user message for multi-turn caching.
        This allows the conversation context to be cached and reused.
        """
        if not enable_caching or not messages:
            return messages

        # Find the last user message and add cache control
        result = []
        last_user_idx = -1
        for i, msg in enumerate(messages):
            if msg.get("role") == "user":
                last_user_idx = i

        for i, msg in enumerate(messages):
            if i == last_user_idx and msg.get("role") == "user":
                # Convert simple content to content blocks with cache_control
                content = msg.get("content", "")
                if isinstance(content, str):
                    result.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": content,
                                    "cache_control": {"type": cache_ttl},
                                }
                            ],
                        }
                    )
                else:
                    # Already a list of content blocks, add cache to last text block
                    new_content = []
                    for j, block in enumerate(content):
                        if j == len(content) - 1 and block.get("type") == "text":
                            new_content.append({**block, "cache_control": {"type": cache_ttl}})
                        else:
                            new_content.append(block)
                    result.append({"role": "user", "content": new_content})
            else:
                result.append(msg)

        return result

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        enable_caching: bool = True,
        cache_ttl: CacheTTL = "ephemeral",
        **kwargs: Any,
    ) -> CompletionResult:
        """
        Generate completion using Claude.

        Uses OAuth via Claude SDK if available, otherwise falls back to API key.

        Args:
            messages: Conversation messages
            model: Model identifier
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            enable_caching: Enable prompt caching (API key mode only)
            cache_ttl: Cache TTL - "ephemeral" (5min) or "1h" (1 hour)
            **kwargs: Additional parameters

        Returns:
            CompletionResult with cache metrics if caching enabled
        """
        if self._use_oauth:
            return await self._complete_oauth(messages, model, max_tokens, **kwargs)
        else:
            return await self._complete_api_key(
                messages, model, max_tokens, temperature, enable_caching, cache_ttl, **kwargs
            )

    async def _complete_oauth(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> CompletionResult:
        """Complete using OAuth via Claude Agent SDK."""
        import time

        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        start_time = time.time()

        # Map model to SDK short name
        sdk_model = self.MODEL_MAP.get(model, model)

        # Build prompt from messages
        system_parts = []
        prompt_parts = []
        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            elif msg.role == "user":
                prompt_parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                prompt_parts.append(f"Assistant: {msg.content}")

        full_prompt = "\n".join(system_parts + prompt_parts)
        if not full_prompt.strip():
            full_prompt = "Hello"

        options = ClaudeAgentOptions(
            cwd=kwargs.get("working_dir", "."),
            permission_mode="bypassPermissions",  # For simple queries
            cli_path=self._cli_path,
            model=sdk_model,
        )

        content_parts = []
        try:
            client = ClaudeSDKClient(options=options)
            async with client:
                await client.query(full_prompt)

                async for msg in client.receive_response():
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock):
                                content_parts.append(block.text)

            duration_ms = int((time.time() - start_time) * 1000)
            content = "".join(content_parts)

            logger.info(f"Claude OAuth response: {duration_ms}ms, {len(content)} chars")

            # OAuth doesn't provide detailed usage - estimate from content length
            estimated_output_tokens = len(content) // 4

            return CompletionResult(
                content=content,
                model=f"claude-{sdk_model}",
                provider=self.provider_name,
                input_tokens=0,  # OAuth doesn't expose this
                output_tokens=estimated_output_tokens,
                finish_reason="end_turn",
                raw_response=None,
                cache_metrics=None,  # OAuth doesn't support prompt caching
            )

        except Exception as e:
            logger.error(f"Claude OAuth error: {e}")
            # If OAuth fails and we have API key, fall back
            if self._api_key:
                logger.warning("Falling back to API key mode")
                self._use_oauth = False
                self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
                return await self._complete_api_key(
                    messages, model, max_tokens, 1.0, True, "ephemeral"
                )
            raise ProviderError(
                f"Claude OAuth error: {e}",
                provider=self.provider_name,
                retriable=True,
            ) from e

    async def _complete_api_key(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        enable_caching: bool = True,
        cache_ttl: CacheTTL = "ephemeral",
        tools: list[dict[str, Any]] | None = None,
        enable_programmatic_tools: bool = False,
        container_id: str | None = None,
        **kwargs: Any,
    ) -> CompletionResult:
        """Complete using API key via Anthropic SDK.

        Args:
            messages: Conversation messages
            model: Model identifier
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            enable_caching: Enable prompt caching
            cache_ttl: Cache TTL
            tools: Tool definitions (Claude API format)
            enable_programmatic_tools: If True, uses beta API with code execution
            container_id: Container ID for code execution continuity
            **kwargs: Additional parameters

        Returns:
            CompletionResult with response content and metadata
        """
        # Extract system message and build API messages
        system_content: str | None = None
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                # System messages must be strings
                system_content = msg.content if isinstance(msg.content, str) else str(msg.content)
            else:
                # Handle both string and content block formats
                if isinstance(msg.content, str):
                    api_messages.append({"role": msg.role, "content": msg.content})
                else:
                    # Content blocks (text + images)
                    content_blocks = []
                    for block in msg.content:
                        if isinstance(block, dict):
                            if block.get("type") == "image":
                                # Anthropic format: {type: image, source: {type: base64, media_type, data}}
                                content_blocks.append(block)
                            elif block.get("type") == "text":
                                content_blocks.append(block)
                            else:
                                # Unknown block type, try to include as-is
                                content_blocks.append(block)
                        elif isinstance(block, str):
                            content_blocks.append({"type": "text", "text": block})
                    api_messages.append({"role": msg.role, "content": content_blocks})

        try:
            # Build request params
            params: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": self._prepare_messages_with_cache(
                    api_messages, enable_caching, cache_ttl
                ),
            }

            # Add system message with cache control
            if system_content:
                if enable_caching:
                    params["system"] = [
                        {
                            "type": "text",
                            "text": system_content,
                            "cache_control": {"type": cache_ttl},
                        }
                    ]
                else:
                    params["system"] = system_content

            # Add tools if provided
            if tools:
                params["tools"] = tools

            # Add container for code execution continuity
            if container_id:
                params["container"] = container_id

            # Extended thinking support
            thinking_budget = kwargs.get("budget_tokens")
            if thinking_budget:
                params["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": thinking_budget,
                }
                # Must use temperature 1.0 with thinking
                params["temperature"] = 1.0
                logger.info(f"Extended thinking enabled with {thinking_budget} token budget")

            # Determine if beta API is needed
            betas: list[str] = []
            if enable_programmatic_tools:
                betas.append("advanced-tool-use-2025-11-20")
            if thinking_budget and tools:
                # Interleaved thinking with tools
                betas.append("interleaved-thinking-2025-05-14")

            # Make API call
            if betas:
                response = await self._client.beta.messages.create(betas=betas, **params)
            else:
                # Standard API call
                response = await self._client.messages.create(**params)

            # Extract content, thinking blocks, and tool calls
            content = ""
            thinking_content = ""
            tool_calls_result: list[ToolCallResult] = []
            if response.content:
                for block in response.content:
                    block_type = getattr(block, "type", None)
                    if block_type == "thinking":
                        # Extended thinking block
                        thinking_content += getattr(block, "thinking", "")
                    elif hasattr(block, "text"):
                        content += block.text
                    elif block_type == "tool_use":
                        # Extract caller info (programmatic tool calling)
                        caller = getattr(block, "caller", None)
                        caller_type = "direct"
                        caller_tool_id = None
                        if caller:
                            caller_type = getattr(caller, "type", "direct")
                            caller_tool_id = getattr(caller, "tool_id", None)
                        tool_calls_result.append(
                            ToolCallResult(
                                id=block.id,
                                name=block.name,
                                input=block.input,
                                caller_type=caller_type,
                                caller_tool_id=caller_tool_id,
                            )
                        )

            # Extract container info (programmatic tool calling)
            container_state = None
            container_resp = getattr(response, "container", None)
            if container_resp:
                container_state = ContainerState(
                    id=getattr(container_resp, "id", ""),
                    expires_at=getattr(container_resp, "expires_at", ""),
                )

            # Extract cache metrics
            cache_metrics = None
            if enable_caching:
                cache_metrics = CacheMetrics(
                    cache_creation_input_tokens=getattr(
                        response.usage, "cache_creation_input_tokens", 0
                    )
                    or 0,
                    cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0)
                    or 0,
                )
                if cache_metrics.cache_read_input_tokens > 0:
                    logger.info(
                        f"Cache hit: {cache_metrics.cache_read_input_tokens} tokens "
                        f"({cache_metrics.cache_hit_rate:.1%} hit rate)"
                    )

            # Extract thinking tokens from usage if available
            thinking_input_tokens = getattr(response.usage, "cache_creation_input_tokens", None)
            if thinking_content:
                logger.info(f"Extended thinking used: {len(thinking_content)} chars")

            return CompletionResult(
                content=content,
                model=response.model,
                provider=self.provider_name,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                finish_reason=response.stop_reason,
                raw_response=response,
                cache_metrics=cache_metrics,
                tool_calls=tool_calls_result if tool_calls_result else None,
                container=container_state,
                thinking_content=thinking_content if thinking_content else None,
                thinking_tokens=thinking_input_tokens,
            )

        except anthropic.RateLimitError as e:
            logger.warning(f"Claude rate limit: {e}")
            # Try to extract retry-after from response
            retry_after = None
            if hasattr(e, "response") and e.response:
                retry_after_str = e.response.headers.get("retry-after")
                if retry_after_str:
                    try:
                        retry_after = float(retry_after_str)
                    except ValueError:
                        pass
            raise RateLimitError(self.provider_name, retry_after) from e

        except anthropic.AuthenticationError as e:
            logger.error(f"Claude auth error: {e}")
            raise AuthenticationError(self.provider_name) from e

        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise ProviderError(
                str(e),
                provider=self.provider_name,
                retriable=getattr(e, "status_code", 500) >= 500,
                status_code=getattr(e, "status_code", None),
            ) from e

    async def health_check(self) -> bool:
        """Check if Claude is reachable."""
        if self._use_oauth:
            # For OAuth, just check CLI exists
            return self._cli_path is not None
        else:
            try:
                # Use a minimal request to check connectivity
                await self._client.messages.create(
                    model="claude-haiku-4-5-20250514",
                    max_tokens=10,
                    messages=[{"role": "user", "content": "ping"}],
                )
                return True
            except Exception as e:
                logger.warning(f"Claude health check failed: {e}")
                return False

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """
        Stream completion from Claude.

        OAuth mode uses polling. API key mode uses native streaming.
        """
        if self._use_oauth:
            # OAuth mode: poll for response chunks
            async for event in self._stream_oauth(messages, model, max_tokens, **kwargs):
                yield event
        else:
            # API key mode: native streaming
            async for event in self._stream_api_key(
                messages, model, max_tokens, temperature, **kwargs
            ):
                yield event

    async def _stream_oauth(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream using OAuth via Claude Agent SDK."""
        from claude_agent_sdk import ClaudeAgentOptions, query
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        # Map model to SDK short name
        sdk_model = self.MODEL_MAP.get(model, model)

        # Build prompt from messages
        system_parts = []
        prompt_parts = []
        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            elif msg.role == "user":
                prompt_parts.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                prompt_parts.append(f"Assistant: {msg.content}")

        full_prompt = "\n".join(system_parts + prompt_parts)

        options = ClaudeAgentOptions(
            cwd=kwargs.get("working_dir", "."),
            permission_mode="bypassPermissions",
            cli_path=self._cli_path,
            model=sdk_model,
        )

        total_content = ""
        try:
            async for message in query(prompt=full_prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            total_content += block.text
                            yield StreamEvent(type="content", content=block.text)

            yield StreamEvent(
                type="done",
                input_tokens=0,
                output_tokens=len(total_content) // 4,
                finish_reason="end_turn",
            )

        except Exception as e:
            logger.error(f"Claude OAuth stream error: {e}")
            yield StreamEvent(type="error", error=str(e))

    async def _stream_api_key(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream using API key via Anthropic SDK."""
        # Extract system message and build API messages
        system_content: str | None = None
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                # System messages must be strings
                system_content = msg.content if isinstance(msg.content, str) else str(msg.content)
            else:
                # Handle both string and content block formats
                if isinstance(msg.content, str):
                    api_messages.append({"role": msg.role, "content": msg.content})
                else:
                    # Content blocks (text + images)
                    content_blocks = []
                    for block in msg.content:
                        if isinstance(block, dict):
                            if block.get("type") == "image" or block.get("type") == "text":
                                content_blocks.append(block)
                            else:
                                content_blocks.append(block)
                        elif isinstance(block, str):
                            content_blocks.append({"type": "text", "text": block})
                    api_messages.append({"role": msg.role, "content": content_blocks})

        try:
            # Build request params
            params: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": api_messages,
                "stream": True,
            }

            if system_content:
                params["system"] = system_content

            # Create streaming message
            async with self._client.messages.stream(**params) as stream:
                async for event in stream:
                    if event.type == "content_block_delta":
                        if hasattr(event.delta, "text"):
                            yield StreamEvent(type="content", content=event.delta.text)

                # Get final message for complete token counts
                final_message = await stream.get_final_message()
                yield StreamEvent(
                    type="done",
                    input_tokens=final_message.usage.input_tokens,
                    output_tokens=final_message.usage.output_tokens,
                    finish_reason=final_message.stop_reason,
                )

        except anthropic.RateLimitError as e:
            logger.warning(f"Claude rate limit (stream): {e}")
            yield StreamEvent(type="error", error=f"Rate limit exceeded: {e}")

        except anthropic.AuthenticationError as e:
            logger.error(f"Claude auth error (stream): {e}")
            yield StreamEvent(type="error", error=f"Authentication failed: {e}")

        except anthropic.APIError as e:
            logger.error(f"Claude API error (stream): {e}")
            yield StreamEvent(type="error", error=str(e))

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        write_enabled: bool = False,
        yolo_mode: bool = False,
        working_dir: str | None = None,
        max_tokens: int = 4096,
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
            max_tokens: Maximum tokens in response
            **kwargs: Additional parameters

        Yields:
            Tuple of (SDK message object, session_id).
            session_id is populated from init and included with each yield.
        """
        if not self._use_oauth:
            raise ProviderError(
                "Tool calling requires OAuth mode (Claude CLI)",
                provider=self.provider_name,
                retriable=False,
            )

        from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, query

        permission_callback = self._permission_callback

        async def permission_hook(
            input_data: dict[str, Any],
            tool_use_id: str | None,
            context: Any,
        ) -> dict[str, Any]:
            """PreToolUse hook for permission control."""
            tool_name = input_data.get("tool_name", "")
            tool_input = input_data.get("tool_input", {})
            hook_event_name = input_data.get("hook_event_name", "PreToolUse")

            # Read tools always allowed
            if tool_name in READ_TOOLS:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": hook_event_name,
                        "permissionDecision": "allow",
                    }
                }

            # Write tools need permission
            if tool_name in WRITE_TOOLS:
                if not write_enabled:
                    return {
                        "hookSpecificOutput": {
                            "hookEventName": hook_event_name,
                            "permissionDecision": "deny",
                            "permissionDecisionReason": "Write access not enabled",
                        }
                    }

                if yolo_mode:
                    return {
                        "hookSpecificOutput": {
                            "hookEventName": hook_event_name,
                            "permissionDecision": "allow",
                        }
                    }

                # Use permission callback if available
                if permission_callback:
                    try:
                        approved = await permission_callback(tool_name, tool_input)
                        decision = "allow" if approved else "deny"
                        result: dict[str, Any] = {
                            "hookSpecificOutput": {
                                "hookEventName": hook_event_name,
                                "permissionDecision": decision,
                            }
                        }
                        if not approved:
                            result["hookSpecificOutput"]["permissionDecisionReason"] = (
                                "Permission denied by user"
                            )
                        return result
                    except Exception as e:
                        logger.error(f"Permission callback error: {e}")
                        return {
                            "hookSpecificOutput": {
                                "hookEventName": hook_event_name,
                                "permissionDecision": "deny",
                                "permissionDecisionReason": f"Permission callback error: {e}",
                            }
                        }

                # No callback - deny for safety
                return {
                    "hookSpecificOutput": {
                        "hookEventName": hook_event_name,
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "Permission required but no callback",
                    }
                }

            # Unknown tools - allow
            return {}

        after_tool_callback = self._after_tool_callback

        async def post_tool_hook(
            input_data: dict[str, Any],
            tool_use_id: str | None,
            context: Any,
        ) -> dict[str, Any]:
            """PostToolUse hook for observation capture."""
            if not after_tool_callback:
                return {}

            tool_name = input_data.get("tool_name", "")
            tool_input = input_data.get("tool_input", {})
            tool_output = input_data.get("tool_output", "")

            try:
                await after_tool_callback(tool_name, tool_input, tool_output)
            except Exception as e:
                logger.warning(f"After tool callback error: {e}")

            return {}

        # Build hooks
        hooks: dict[str, list[HookMatcher]] = {"PreToolUse": [HookMatcher(hooks=[permission_hook])]}
        if after_tool_callback:
            hooks["PostToolUse"] = [HookMatcher(hooks=[post_tool_hook])]

        # Map model to SDK name
        sdk_model = self.MODEL_MAP.get(model, model)

        options = ClaudeAgentOptions(
            cwd=working_dir or ".",
            cli_path=self._cli_path,
            model=sdk_model,
            hooks=hooks,
        )

        # Build prompt from messages
        system_parts = []
        prompt_parts = []
        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            elif msg.role == "user":
                prompt_parts.append(msg.content)

        full_prompt = "\n".join(system_parts + prompt_parts)

        session_id: str | None = None
        try:
            async for message in query(prompt=full_prompt, options=options):
                # Capture session ID from init
                if (
                    hasattr(message, "subtype")
                    and message.subtype == "init"
                    and hasattr(message, "data")
                ):
                    session_id = message.data.get("session_id")
                    if session_id:
                        logger.info(f"Claude SDK session ID: {session_id}")

                yield (message, session_id)

        except Exception as e:
            logger.error(f"Claude tool error: {e}")
            raise ProviderError(
                f"Claude tool error: {e}",
                provider=self.provider_name,
                retriable=True,
            ) from e
