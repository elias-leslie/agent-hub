"""Claude adapter with OAuth via Claude SDK (zero API cost)."""

import logging
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, ClassVar

from app.adapters.base import (
    CompletionResult,
    Message,
    ProviderAdapter,
    ProviderError,
    StreamEvent,
)

logger = logging.getLogger(__name__)

# Tool categories for permission handling
READ_TOOLS = {"read_file", "search_code", "list_files", "get_project_structure"}
WRITE_TOOLS = {"write_file", "edit_file", "delete_file", "create_directory"}

# Thinking level to budget tokens mapping for Claude
# Matches Auto-Claude's THINKING_BUDGET_MAP for consistency
THINKING_LEVEL_BUDGETS = {
    "minimal": None,  # Disabled
    "low": 1024,
    "medium": 4096,
    "high": 16384,
    "ultrathink": 65536,
}


def _get_claude_thinking_budget(thinking_level: str | None) -> int | None:
    """Convert thinking_level to Claude's token budget.

    Args:
        thinking_level: Semantic level (minimal/low/medium/high/ultrathink)

    Returns:
        Token budget for Claude's max_thinking_tokens, or None to disable
    """
    if thinking_level:
        return THINKING_LEVEL_BUDGETS.get(thinking_level)
    return None


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
        max_tokens: int = 4096,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> CompletionResult:
        """
        Generate completion using Claude via OAuth.

        Args:
            messages: Conversation messages
            model: Model identifier
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (unused in OAuth mode)
            **kwargs: Additional parameters

        Returns:
            CompletionResult
        """
        return await self._complete_oauth(messages, model, max_tokens, **kwargs)

    def _extract_json_from_response(self, content: str) -> str:
        """Extract JSON from a response that may have surrounding text or markdown.

        Args:
            content: Raw response content that should contain JSON

        Returns:
            Extracted JSON string, or original content if extraction fails
        """
        import json
        import re

        content = content.strip()

        # Try parsing as-is first
        try:
            json.loads(content)
            return content
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code blocks
        # Match ```json ... ``` or ``` ... ```
        code_block_pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?```"
        matches = re.findall(code_block_pattern, content)
        for match in matches:
            try:
                json.loads(match.strip())
                logger.info("Extracted JSON from markdown code block")
                return match.strip()
            except json.JSONDecodeError:
                continue

        # Try finding JSON object pattern { ... }
        brace_pattern = r"\{[\s\S]*\}"
        matches = re.findall(brace_pattern, content)
        for match in matches:
            try:
                json.loads(match)
                logger.info("Extracted JSON object from response")
                return match
            except json.JSONDecodeError:
                continue

        # Try finding JSON array pattern [ ... ]
        bracket_pattern = r"\[[\s\S]*\]"
        matches = re.findall(bracket_pattern, content)
        for match in matches:
            try:
                json.loads(match)
                logger.info("Extracted JSON array from response")
                return match
            except json.JSONDecodeError:
                continue

        # Return original if no valid JSON found
        logger.warning("Could not extract valid JSON from response")
        return content

    async def _complete_oauth(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> CompletionResult:
        """Complete using OAuth via Claude Agent SDK.

        For structured output (JSON mode), uses native SDK output_format parameter
        which enforces JSON schema validation via StructuredOutput tool.
        """
        import json
        import time

        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
        from claude_agent_sdk.types import AssistantMessage, TextBlock

        start_time = time.time()

        # Map model to SDK short name
        sdk_model = self.MODEL_MAP.get(model, model)

        # Check for structured output (JSON mode) request
        response_format = kwargs.get("response_format")
        json_mode = response_format is not None and response_format.get("type") == "json_object"
        json_schema = response_format.get("schema") if json_mode and response_format else None

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

        # Extended thinking support via OAuth
        thinking_budget = _get_claude_thinking_budget(kwargs.get("thinking_level"))

        # Build SDK options
        sdk_options: dict[str, Any] = {
            "cwd": kwargs.get("working_dir", "."),
            "permission_mode": "bypassPermissions",  # For simple queries
            "cli_path": self._cli_path,
            "model": sdk_model,
            "max_thinking_tokens": thinking_budget,  # Extended thinking via OAuth
        }

        # Native structured output via SDK output_format (preferred approach)
        # SDK uses StructuredOutput tool internally for schema validation
        if json_mode and json_schema:
            sdk_options["output_format"] = {
                "type": "json_schema",
                "schema": json_schema,
            }
            # Structured output requires extra turn for tool response
            sdk_options["max_turns"] = 2
            logger.info("OAuth: Structured output enabled via native SDK output_format")

        options = ClaudeAgentOptions(**sdk_options)

        content_parts = []
        thinking_parts = []
        structured_output: dict[str, Any] | None = None
        try:
            client = ClaudeSDKClient(options=options)
            async with client:
                await client.query(full_prompt)

                async for msg in client.receive_response():
                    msg_type = type(msg).__name__

                    # Extract thinking blocks (ThinkingBlock or type="thinking")
                    if msg_type == "ThinkingBlock" or (
                        hasattr(msg, "type") and msg.type == "thinking"
                    ):
                        thinking_text = getattr(msg, "thinking", "") or getattr(msg, "text", "")
                        if thinking_text:
                            thinking_parts.append(thinking_text)
                            logger.info(f"Claude OAuth thinking: {len(thinking_text)} chars")

                    # Check for StructuredOutput tool use block (SDK output_format mechanism)
                    if msg_type == "ToolUseBlock" or (
                        hasattr(msg, "type") and msg.type == "tool_use"
                    ):
                        tool_name = getattr(msg, "name", "")
                        if tool_name == "StructuredOutput":
                            tool_input = getattr(msg, "input", {})
                            if tool_input:
                                structured_output = tool_input
                                logger.info("OAuth: Extracted structured output from ToolUseBlock")

                    # Extract text content from AssistantMessage
                    if isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock):
                                content_parts.append(block.text)
                            # Check for StructuredOutput tool use within AssistantMessage content
                            block_type = type(block).__name__
                            if (
                                block_type == "ToolUseBlock"
                                or getattr(block, "type", "") == "tool_use"
                            ):
                                tool_name = getattr(block, "name", "")
                                if tool_name == "StructuredOutput":
                                    tool_input = getattr(block, "input", {})
                                    if tool_input and structured_output is None:
                                        structured_output = tool_input
                                        logger.info(
                                            "OAuth: Extracted structured output from AssistantMessage content"
                                        )
                            # Also check for thinking blocks within content
                            if (
                                block_type == "ThinkingBlock"
                                or getattr(block, "type", "") == "thinking"
                            ):
                                thinking_text = getattr(block, "thinking", "") or getattr(
                                    block, "text", ""
                                )
                                if thinking_text and thinking_text not in thinking_parts:
                                    thinking_parts.append(thinking_text)

                    # Check for structured_output attribute on ResultMessage
                    if (
                        hasattr(msg, "structured_output")
                        and msg.structured_output
                        and structured_output is None
                    ):
                        structured_output = msg.structured_output
                        logger.info("OAuth: Extracted structured output from ResultMessage")

            duration_ms = int((time.time() - start_time) * 1000)
            content = "".join(content_parts)
            thinking_content = "\n".join(thinking_parts) if thinking_parts else None

            # For structured output, use the extracted structured data
            if json_mode:
                if structured_output:
                    # Native SDK structured output succeeded
                    content = json.dumps(structured_output, indent=2)
                    logger.info(f"OAuth: Using native structured output ({len(content)} chars)")
                elif content:
                    # Fallback: Try to extract JSON from text response
                    content = self._extract_json_from_response(content)
                    logger.info("OAuth: Falling back to prompt-based JSON extraction")

            if thinking_content:
                logger.info(
                    f"Claude OAuth response: {duration_ms}ms, {len(content)} chars, thinking: {len(thinking_content)} chars"
                )
            else:
                logger.info(f"Claude OAuth response: {duration_ms}ms, {len(content)} chars")

            # Estimate tokens from content length
            estimated_output_tokens = len(content) // 4
            thinking_tokens_estimate = len(thinking_content) // 4 if thinking_content else None

            return CompletionResult(
                content=content,
                model=f"claude-{sdk_model}",
                provider=self.provider_name,
                input_tokens=0,  # OAuth doesn't expose this
                output_tokens=estimated_output_tokens,
                finish_reason="end_turn",
                raw_response=None,
                cache_metrics=None,  # OAuth doesn't support prompt caching
                thinking_content=thinking_content,
                thinking_tokens=thinking_tokens_estimate,
            )

        except Exception as e:
            logger.error(f"Claude OAuth error: {e}")
            raise ProviderError(
                f"Claude OAuth error: {e}",
                provider=self.provider_name,
                retriable=True,
            ) from e


    async def health_check(self) -> bool:
        """Check if Claude is reachable (OAuth mode)."""
        # For OAuth, just check CLI exists
        return self._cli_path is not None

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """
        Stream completion from Claude via OAuth.
        """
        async for event in self._stream_oauth(messages, model, max_tokens, **kwargs):
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
