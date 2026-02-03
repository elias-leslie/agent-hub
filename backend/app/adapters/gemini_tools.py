"""Tool execution support for Gemini adapter."""

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

from google import genai
from google.genai import types

from app.adapters.base import Message, ProviderError
from app.adapters.gemini_events import MockContentBlock, MockEvent, MockMessage
from app.adapters.gemini_thinking import get_thinking_level
from app.adapters.gemini_utils import convert_messages
from app.services.tools import ToolCall
from app.services.tools.direct_executor import DirectToolHandler

logger = logging.getLogger(__name__)


async def execute_tool_loop(
    client: genai.Client,
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    working_dir: str | None,
    max_tokens: int,
    max_turns: int,
    provider_name: str,
    **kwargs: Any,
) -> AsyncIterator[tuple[Any, str]]:
    """Run agentic loop with tool execution.

    Args:
        client: Gemini client instance
        messages: Conversation messages
        model: Model identifier
        tools: Tool definitions in Gemini format
        working_dir: Working directory for tool execution
        max_tokens: Maximum tokens per response
        max_turns: Maximum agentic turns
        provider_name: Provider name for errors
        **kwargs: Additional parameters

    Yields:
        Tuple of (event_object, session_id) similar to Claude SDK format
    """
    # Initialize direct tool handler
    tool_handler = DirectToolHandler(working_dir)

    # Generate unique session ID
    session_id = str(uuid.uuid4())

    # Build Gemini tools from definitions
    gemini_tools: list[types.Tool] = []
    for tool_def in tools:
        function_decl = types.FunctionDeclaration(
            name=tool_def.get("name", ""),
            description=tool_def.get("description", ""),
            parameters=tool_def.get("input_schema") or tool_def.get("parameters", {}),
        )
        gemini_tools.append(types.Tool(function_declarations=[function_decl]))

    # Build initial conversation contents
    system_instruction, contents = convert_messages(messages)

    turn = 0
    accumulated_text = ""

    try:
        while turn < max_turns:
            turn += 1

            # Build config
            config = types.GenerateContentConfig(
                temperature=1.0,
                max_output_tokens=max_tokens,
                tools=cast(Any, gemini_tools) if gemini_tools else None,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )

            # Gemini 3 models require thinking_config with thinking_level
            thinking_level = get_thinking_level(model, kwargs.get("thinking_level"))
            if thinking_level:
                config.thinking_config = types.ThinkingConfig(
                    thinking_level=thinking_level,
                )

            if system_instruction:
                config.system_instruction = system_instruction

            # Make API call
            response = await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

            # Check for valid response
            if not response.candidates or not response.candidates[0].content:
                yield (MockEvent(type="error", error="Empty response from model"), session_id)
                return

            candidate = response.candidates[0]
            response_parts: list[types.Part] = (
                list(candidate.content.parts)
                if candidate.content and candidate.content.parts
                else []
            )

            # Process response parts
            text_content = ""
            tool_calls: list[ToolCall] = []

            for part in response_parts:
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
            if candidate.content:
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
            provider=provider_name,
            retriable=True,
        ) from e
