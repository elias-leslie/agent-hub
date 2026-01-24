"""Gemini adapter using Google GenAI SDK."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from google import genai
from google.genai import types
from google.genai.types import HttpOptions

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    Message,
    ProviderAdapter,
    ProviderError,
    RateLimitError,
    StreamEvent,
    ToolCallResult,
    with_retry,
)
from app.config import settings

logger = logging.getLogger(__name__)

# Gemini 3 thinking level mappings
# Gemini 3 Pro: supports "low", "high"
# Gemini 3 Flash: supports "minimal", "low", "medium", "high"
# Reference: https://ai.google.dev/gemini-api/docs/gemini-3
GEMINI_3_PRO_THINKING_LEVELS = {"low", "high"}
GEMINI_3_FLASH_THINKING_LEVELS = {"minimal", "low", "medium", "high"}

# Map unified API thinking levels to Gemini-specific levels
# Unified levels: minimal, low, medium, high, ultrathink
THINKING_LEVEL_MAP_PRO = {
    "minimal": "low",  # Pro doesn't support minimal, use low
    "low": "low",
    "medium": "high",  # Pro doesn't support medium, use high
    "high": "high",
    "ultrathink": "high",  # Pro max is high
}

THINKING_LEVEL_MAP_FLASH = {
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "ultrathink": "high",  # Flash max is high
}


def _get_gemini_thinking_level(model: str, thinking_level: str | None) -> str | None:
    """Convert thinking_level to Gemini-compatible value.

    Args:
        model: Model name (e.g., "gemini-3-pro-preview")
        thinking_level: User-specified thinking level (minimal/low/medium/high/ultrathink)

    Returns:
        Gemini-compatible thinking_level string, or None if not requested
    """
    # Only enable thinking if explicitly requested
    # Thinking tokens count against max_tokens, so don't enable by default
    if not thinking_level:
        return None

    # Only Gemini 3 models support thinking config
    is_gemini_3 = "3" in model
    if not is_gemini_3:
        return None

    is_pro = "pro" in model.lower()
    level_map = THINKING_LEVEL_MAP_PRO if is_pro else THINKING_LEVEL_MAP_FLASH

    return level_map.get(thinking_level, "high")


class GeminiAdapter(ProviderAdapter):
    """Adapter for Gemini models via Google GenAI API."""

    def __init__(
        self,
        api_key: str | None = None,
        before_tool_callback: (Callable[[str, dict[str, Any]], Awaitable[bool]] | None) = None,
        after_tool_callback: (Callable[[str, dict[str, Any], str], Awaitable[None]] | None) = None,
    ):
        """
        Initialize Gemini adapter.

        Args:
            api_key: Google API key. Falls back to settings if not provided.
            before_tool_callback: Async callback before tool execution.
                Called with (tool_name, tool_args), returns True to allow.
            after_tool_callback: Async callback after tool execution.
                Called with (tool_name, tool_input, tool_output).
        """
        self._api_key = api_key or settings.gemini_api_key
        if not self._api_key:
            raise ValueError("Google API key not configured")
        # SDK-level timeout for TRUE idle detection at transport layer (90s based on profiling)
        # Note: HttpOptions timeout is in milliseconds
        self._client = genai.Client(
            api_key=self._api_key,
            http_options=HttpOptions(timeout=90_000),  # 90 seconds in ms
        )
        self._before_tool_callback = before_tool_callback
        self._after_tool_callback = after_tool_callback

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _build_parts(self, content: str | list[dict[str, Any]]) -> list[types.Part]:
        """Build Gemini parts from content.

        Args:
            content: Either a string or list of content blocks (text/image).

        Returns:
            List of Gemini Part objects.
        """
        if isinstance(content, str):
            return [types.Part(text=content)]

        parts: list[types.Part] = []
        for block in content:
            if isinstance(block, str):
                parts.append(types.Part(text=block))
            elif isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "text":
                    parts.append(types.Part(text=block.get("text", "")))
                elif block_type == "image":
                    # Extract image data from source
                    source = block.get("source", {})
                    if source.get("type") == "base64":
                        import base64

                        media_type = source.get("media_type", "image/png")
                        data = source.get("data", "")
                        # Gemini expects raw bytes for inline_data
                        image_bytes = base64.b64decode(data)
                        parts.append(types.Part.from_bytes(data=image_bytes, mime_type=media_type))
        return parts

    @with_retry
    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate completion using Gemini API."""
        # Extract system message and build content
        system_instruction: str | None = None
        contents: list[types.Content] = []

        for msg in messages:
            if msg.role == "system":
                # System messages must be strings
                system_instruction = (
                    msg.content if isinstance(msg.content, str) else str(msg.content)
                )
            else:
                # Map roles: user -> user, assistant -> model
                role = "model" if msg.role == "assistant" else "user"
                parts = self._build_parts(msg.content)
                contents.append(types.Content(role=role, parts=parts))

        # Extract tools if provided
        tools_param = kwargs.get("tools")

        # Extract structured output config
        response_format = kwargs.get("response_format")

        try:
            # Build config - disable AFC to prevent internal polling loops
            config_params: dict[str, Any] = {
                "temperature": temperature,
                "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
            }
            # Only pass max_output_tokens when explicitly set
            if max_tokens is not None:
                config_params["max_output_tokens"] = max_tokens

            config = types.GenerateContentConfig(**config_params)

            # Handle structured output (JSON mode)
            if response_format and response_format.get("type") == "json_object":
                config.response_mime_type = "application/json"
                json_schema = response_format.get("schema")
                if json_schema:
                    config.response_schema = json_schema
                    logger.info("Gemini structured output enabled with JSON schema")
                else:
                    logger.info("Gemini structured output enabled (JSON mode without schema)")

            # Gemini 3 models require thinking_config with thinking_level (not thinking_budget)
            # Reference: https://ai.google.dev/gemini-api/docs/gemini-3
            # - Gemini 3 Pro: supports "low", "high" (high is default)
            # - Gemini 3 Flash: supports "minimal", "low", "medium", "high"
            # Note: thinking_budget is deprecated for Gemini 3; use thinking_level instead
            thinking_level = _get_gemini_thinking_level(model, kwargs.get("thinking_level"))
            if thinking_level:
                config.thinking_config = types.ThinkingConfig(
                    thinking_level=thinking_level,
                )
                logger.debug(f"Gemini thinking_level={thinking_level} for model={model}")

            if system_instruction:
                config.system_instruction = system_instruction

            # Add tools to config if provided
            if tools_param:
                config.tools = tools_param

            # Make API call (google-genai supports both sync and async)
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

            # Extract content, thinking, and tool calls from response parts
            content = ""
            thinking_content = ""
            tool_calls: list[ToolCallResult] = []

            if (
                response.candidates
                and response.candidates[0].content
                and response.candidates[0].content.parts
            ):
                for part in response.candidates[0].content.parts:
                    # Check if this is a thinking part (part.thought == True)
                    if getattr(part, "thought", False) and part.text:
                        thinking_content += part.text
                    elif part.text:
                        content += part.text
                    elif part.function_call:
                        fc = part.function_call
                        args = dict(fc.args) if fc.args else {}
                        call_id = fc.id or fc.name or "unknown"
                        tool_calls.append(
                            ToolCallResult(
                                id=call_id,
                                name=fc.name or "unknown",
                                input=args,
                            )
                        )

            # Fallback to response.text if no parts
            if not content and response.text:
                content = response.text

            # Extract token counts from usage metadata
            input_tokens = 0
            output_tokens = 0
            thoughts_token_count = None
            if response.usage_metadata:
                input_tokens = response.usage_metadata.prompt_token_count or 0
                output_tokens = response.usage_metadata.candidates_token_count or 0
                # Capture thinking tokens if available (Gemini 2.5+ with thinking enabled)
                thoughts_token_count = getattr(
                    response.usage_metadata, "thoughts_token_count", None
                )
                if thoughts_token_count:
                    logger.info(f"Gemini thinking: {thoughts_token_count} tokens used")

            # Determine finish reason
            finish_reason = None
            if response.candidates and response.candidates[0].finish_reason:
                finish_reason = str(response.candidates[0].finish_reason)

            # Use API-provided thinking tokens if available, otherwise estimate from content
            thinking_tokens = thoughts_token_count
            if not thinking_tokens and thinking_content:
                thinking_tokens = len(thinking_content) // 4
                logger.info(
                    f"Gemini thinking (from content): {len(thinking_content)} chars, ~{thinking_tokens} tokens"
                )

            return CompletionResult(
                content=content,
                model=model,
                provider=self.provider_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
                raw_response=response,
                tool_calls=tool_calls if tool_calls else None,
                thinking_content=thinking_content if thinking_content else None,
                thinking_tokens=thinking_tokens,
            )

        except Exception as e:
            error_str = str(e).lower()

            # Check for rate limit errors
            if "429" in str(e) or "rate" in error_str or "quota" in error_str:
                logger.warning(f"Gemini rate limit: {e}")
                raise RateLimitError(self.provider_name) from e

            # Check for auth errors
            if "401" in str(e) or "403" in str(e) or "api key" in error_str:
                logger.error(f"Gemini auth error: {e}")
                raise AuthenticationError(self.provider_name) from e

            # Generic provider error
            logger.error(f"Gemini API error: {e}")
            raise ProviderError(
                str(e),
                provider=self.provider_name,
                retriable="500" in str(e) or "503" in str(e),
            ) from e

    async def health_check(self) -> bool:
        """Check if Gemini API is reachable."""
        try:
            # Use a minimal request to check connectivity
            from app.constants import GEMINI_FLASH

            response = await self._client.aio.models.generate_content(
                model=GEMINI_FLASH,
                contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
                config=types.GenerateContentConfig(max_output_tokens=50),
            )
            # Check for valid response (text or candidates)
            return response.text is not None or bool(response.candidates)
        except Exception as e:
            logger.warning(f"Gemini health check failed: {e}")
            return False

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream completion from Gemini API."""
        # Extract system message and build content
        system_instruction: str | None = None
        contents: list[types.Content] = []

        for msg in messages:
            if msg.role == "system":
                # System messages must be strings
                system_instruction = (
                    msg.content if isinstance(msg.content, str) else str(msg.content)
                )
            else:
                role = "model" if msg.role == "assistant" else "user"
                parts = self._build_parts(msg.content)
                contents.append(types.Content(role=role, parts=parts))

        try:
            # Build config - disable AFC to prevent internal polling loops
            config_params: dict[str, Any] = {
                "temperature": temperature,
                "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
            }
            # Only pass max_output_tokens when explicitly set
            if max_tokens is not None:
                config_params["max_output_tokens"] = max_tokens

            config = types.GenerateContentConfig(**config_params)

            # Gemini 3 models require thinking_config with thinking_level
            thinking_level = _get_gemini_thinking_level(model, kwargs.get("thinking_level"))
            if thinking_level:
                config.thinking_config = types.ThinkingConfig(
                    thinking_level=thinking_level,
                )

            if system_instruction:
                config.system_instruction = system_instruction

            # Stream response
            total_content = ""
            async for chunk in await self._client.aio.models.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            ):
                if chunk.text:
                    total_content += chunk.text
                    yield StreamEvent(type="content", content=chunk.text)

            # Final event with usage
            input_tokens = 0
            output_tokens = len(total_content) // 4  # Estimate

            yield StreamEvent(
                type="done",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason="STOP",
            )

        except Exception as e:
            logger.error(f"Gemini stream error: {e}")
            yield StreamEvent(type="error", error=str(e))

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        working_dir: str | None = None,
        max_tokens: int = 4096,
        max_turns: int = 20,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        """Run agentic loop with tool execution.

        This method runs a multi-turn conversation loop where:
        1. Send request to Gemini with tools
        2. If model returns tool calls, execute them via sandboxed executor
        3. Send tool results back to model
        4. Repeat until model returns no tool calls

        Args:
            messages: Conversation messages
            model: Model identifier
            tools: Tool definitions in Gemini format
            working_dir: Working directory for tool execution
            max_tokens: Maximum tokens per response
            max_turns: Maximum agentic turns (default 20)
            **kwargs: Additional parameters

        Yields:
            Tuple of (event_object, session_id) similar to Claude SDK format
            Event types: assistant, tool_result, result, error
        """
        from dataclasses import dataclass

        from app.services.tools.sandboxed_executor import (
            SandboxedToolHandler,
            ToolCall,
        )

        @dataclass
        class MockContentBlock:
            type: str
            text: str = ""
            name: str = ""
            input: dict[str, Any] | None = None
            id: str = ""

        @dataclass
        class MockMessage:
            content: list[MockContentBlock]

        @dataclass
        class MockEvent:
            type: str
            subtype: str | None = None
            message: MockMessage | None = None
            content: str = ""
            tool_use_id: str | None = None
            is_error: bool = False
            result: str = ""
            error: str = ""

        # Initialize sandboxed tool handler
        tool_handler = SandboxedToolHandler(working_dir)

        # Generate unique session ID
        import uuid

        session_id = str(uuid.uuid4())

        # Build Gemini tools from definitions
        gemini_tools = []
        for tool_def in tools:
            function_decl = types.FunctionDeclaration(
                name=tool_def.get("name", ""),
                description=tool_def.get("description", ""),
                parameters=tool_def.get("input_schema") or tool_def.get("parameters", {}),
            )
            gemini_tools.append(types.Tool(function_declarations=[function_decl]))

        # Build initial conversation contents
        system_instruction: str | None = None
        contents: list[types.Content] = []

        for msg in messages:
            if msg.role == "system":
                system_instruction = (
                    msg.content if isinstance(msg.content, str) else str(msg.content)
                )
            else:
                role = "model" if msg.role == "assistant" else "user"
                parts = self._build_parts(msg.content)
                contents.append(types.Content(role=role, parts=parts))

        turn = 0
        accumulated_text = ""

        try:
            while turn < max_turns:
                turn += 1

                # Build config
                config = types.GenerateContentConfig(
                    temperature=1.0,
                    max_output_tokens=max_tokens,
                    tools=gemini_tools,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                )

                # Gemini 3 models require thinking_config with thinking_level
                thinking_level = _get_gemini_thinking_level(model, kwargs.get("thinking_level"))
                if thinking_level:
                    config.thinking_config = types.ThinkingConfig(
                        thinking_level=thinking_level,
                    )

                if system_instruction:
                    config.system_instruction = system_instruction

                # Make API call
                response = await self._client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )

                # Check for valid response
                if not response.candidates or not response.candidates[0].content:
                    yield (MockEvent(type="error", error="Empty response from model"), session_id)
                    return

                candidate = response.candidates[0]
                parts = candidate.content.parts if candidate.content else []

                # Process response parts
                text_content = ""
                tool_calls: list[ToolCall] = []

                for part in parts:
                    if part.text:
                        text_content += part.text
                    elif part.function_call:
                        fc = part.function_call
                        tool_id = fc.id or f"{fc.name}_{uuid.uuid4().hex[:8]}"
                        tool_calls.append(
                            ToolCall(
                                id=tool_id,
                                name=fc.name or "unknown",
                                input=dict(fc.args) if fc.args else {},
                            )
                        )

                # Yield text content as assistant message
                if text_content:
                    accumulated_text += text_content
                    yield (
                        MockEvent(
                            type="assistant",
                            message=MockMessage(
                                content=[MockContentBlock(type="text", text=text_content)]
                            ),
                        ),
                        session_id,
                    )

                # Yield tool use events
                for tc in tool_calls:
                    yield (
                        MockEvent(
                            type="assistant",
                            message=MockMessage(
                                content=[
                                    MockContentBlock(
                                        type="tool_use",
                                        name=tc.name,
                                        input=tc.input,
                                        id=tc.id,
                                    )
                                ]
                            ),
                        ),
                        session_id,
                    )

                # If no tool calls, we're done
                if not tool_calls:
                    yield (
                        MockEvent(
                            type="result",
                            subtype="success",
                            result=accumulated_text,
                        ),
                        session_id,
                    )
                    return

                # Execute tools and collect results
                tool_results_parts: list[types.Part] = []

                for tc in tool_calls:
                    # Execute tool
                    result = await tool_handler.execute(tc)

                    # Yield tool result event
                    yield (
                        MockEvent(
                            type="tool_result",
                            content=result.content,
                            tool_use_id=tc.id,
                            is_error=result.is_error,
                        ),
                        session_id,
                    )

                    # Build Gemini function response
                    tool_results_parts.append(
                        types.Part.from_function_response(
                            name=tc.name,
                            response={"result": result.content},
                        )
                    )

                # Add model's response and tool results to conversation
                contents.append(candidate.content)
                contents.append(types.Content(role="user", parts=tool_results_parts))

            # Max turns reached
            yield (
                MockEvent(
                    type="result",
                    subtype="success",
                    result=accumulated_text,
                ),
                session_id,
            )

        except Exception as e:
            logger.error(f"Gemini tool error: {e}")
            yield (
                MockEvent(type="error", error=str(e)),
                session_id,
            )
            raise ProviderError(
                f"Gemini tool error: {e}",
                provider=self.provider_name,
                retriable=True,
            ) from e
