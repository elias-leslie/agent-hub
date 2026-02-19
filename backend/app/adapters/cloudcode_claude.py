"""CloudCode Claude adapter — Claude models via Google CloudCode PA (zero-cost).

Uses the same ``cloudcode-pa.googleapis.com`` endpoint and OAuth credentials
as the Gemini CloudCode path, but applies Claude-specific transforms
(snake_case thinkingConfig, VALIDATED tool mode, interleaved thinking hint).

This gives free access to Claude Sonnet 4.6 and Opus 4.6 (thinking) through
a Google One AI Pro / Gemini Code Assist subscription.
"""

from __future__ import annotations

import logging
import traceback
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import CompletionResult, Message, ProviderAdapter, StreamEvent
from app.adapters.cloudcode_claude_transforms import (
    append_thinking_hint,
    build_claude_generation_config,
    build_claude_tool_config,
    is_thinking_model,
    resolve_cloudcode_model,
)
from app.adapters.gemini_cloudcode import (
    CloudCodeClient,
    build_cloudcode_tools,
    convert_messages_for_cloudcode,
    parse_cloudcode_response,
)
from app.adapters.gemini_events import MockContentBlock, MockEvent, MockMessage
from app.services.tools import ToolCall
from app.services.tools.direct_executor import create_direct_handler

logger = logging.getLogger(__name__)


def _make_cc_client() -> CloudCodeClient | None:
    """Create a CloudCodeClient from existing Gemini OAuth credentials."""
    try:
        from app.adapters.gemini import _resolve_oauth_data

        oauth_data = _resolve_oauth_data()
        if not oauth_data or not oauth_data.get("access_token") or not oauth_data.get("project_id"):
            return None
        return CloudCodeClient(
            access_token=oauth_data["access_token"],
            refresh_token=oauth_data.get("refresh_token"),
            project_id=oauth_data["project_id"],
            expires_at=oauth_data.get("expires_at"),
        )
    except Exception:
        logger.debug("Failed to create CloudCode client for Claude", exc_info=True)
        return None


class CloudCodeClaudeAdapter(ProviderAdapter):
    """Adapter for Claude models via Google CloudCode PA endpoint.

    Reuses the same Gemini OAuth credentials and CloudCodeClient,
    applying Claude-specific request transforms.
    """

    provider_name = "cloudcode"

    def __init__(self) -> None:
        self._cc_client: CloudCodeClient | None = None

    def _ensure_client(self) -> CloudCodeClient:
        """Get or create a CloudCodeClient, refreshing credentials if needed."""
        if self._cc_client is None:
            self._cc_client = _make_cc_client()
        else:
            # Refresh credentials from credential manager
            self._refresh_credentials()

        if self._cc_client is None:
            from app.adapters.base import AuthenticationError
            raise AuthenticationError(provider="cloudcode")
        return self._cc_client

    def _refresh_credentials(self) -> None:
        """Update client credentials from the credential manager."""
        try:
            from app.adapters.gemini import _resolve_oauth_data

            oauth_data = _resolve_oauth_data()
            if oauth_data and self._cc_client is not None:
                if oauth_data.get("access_token"):
                    self._cc_client.access_token = oauth_data["access_token"]
                if oauth_data.get("project_id"):
                    self._cc_client.project_id = oauth_data["project_id"]
                if oauth_data.get("refresh_token"):
                    self._cc_client.refresh_token = oauth_data["refresh_token"]
                if oauth_data.get("expires_at"):
                    self._cc_client.expires_at = oauth_data["expires_at"]
        except Exception:
            logger.debug("CloudCode Claude: credential refresh failed", exc_info=True)

    def _prepare_request(
        self,
        messages: list[Message],
        model: str,
        temperature: float = 1.0,
        max_tokens: int | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]], dict[str, Any] | None, list[dict[str, Any]] | None, dict[str, Any] | None]:
        """Build all request parameters for a Claude CloudCode call.

        Returns:
            (resolved_model, system_instruction, contents, generation_config, tools, tool_config)
        """
        kwargs = kwargs or {}
        resolved = resolve_cloudcode_model(model)
        system_instruction, contents = convert_messages_for_cloudcode(messages)
        generation_config = build_claude_generation_config(
            thinking_level=kwargs.get("thinking_level"),
            max_tokens=max_tokens,
            temperature=temperature,
            model=resolved,
        )

        tools = None
        tool_config = None
        if kwargs.get("tools"):
            tools = build_cloudcode_tools(kwargs["tools"])
            tool_config = build_claude_tool_config()
            # Append thinking hint for thinking models with tools
            if is_thinking_model(resolved):
                system_instruction = append_thinking_hint(system_instruction)

        return resolved, system_instruction, contents, generation_config, tools, tool_config

    # ----- complete -------------------------------------------------------

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        """Non-streaming completion via CloudCode PA with Claude model."""
        client = self._ensure_client()
        resolved, sys_inst, contents, gen_config, tools, tool_config = self._prepare_request(
            messages, model, temperature, max_tokens, kwargs,
        )

        data = await client.generate_content(
            model=resolved,
            contents=contents,
            system_instruction=sys_inst,
            generation_config=gen_config,
            tools=tools,
            tool_config=tool_config,
        )
        return parse_cloudcode_response(data, model, self.provider_name)

    # ----- stream ---------------------------------------------------------

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream completion via CloudCode PA SSE with Claude model."""
        client = self._ensure_client()
        resolved, sys_inst, contents, gen_config, tools, tool_config = self._prepare_request(
            messages, model, temperature, max_tokens, kwargs,
        )

        total_content = ""
        input_tokens = 0
        output_tokens = 0
        finish_reason = "STOP"

        try:
            async for chunk in client.stream_generate_content(
                model=resolved,
                contents=contents,
                system_instruction=sys_inst,
                generation_config=gen_config,
                tools=tools,
                tool_config=tool_config,
            ):
                response = chunk.get("response", chunk)
                candidates = response.get("candidates", [])

                if candidates:
                    candidate = candidates[0]
                    if candidate.get("finishReason"):
                        finish_reason = candidate["finishReason"]

                    parts = (candidate.get("content") or {}).get("parts", [])
                    for part in parts:
                        if part.get("text") and not part.get("thought"):
                            total_content += part["text"]
                            yield StreamEvent(type="content", content=part["text"])
                        elif part.get("functionCall"):
                            fc = part["functionCall"]
                            yield StreamEvent(
                                type="tool_use",
                                tool_id=fc.get("id") or f"tool_{uuid.uuid4().hex[:12]}",
                                tool_name=fc.get("name", "unknown"),
                                tool_input=fc.get("args", {}),
                            )

                usage = response.get("usageMetadata", {})
                if usage.get("promptTokenCount"):
                    input_tokens = usage["promptTokenCount"]
                if usage.get("candidatesTokenCount"):
                    output_tokens = usage["candidatesTokenCount"]

            yield StreamEvent(
                type="done",
                input_tokens=input_tokens,
                output_tokens=output_tokens or len(total_content) // 4,
                finish_reason=finish_reason,
            )
        except Exception as e:
            logger.error("CloudCode Claude stream error: %s", e)
            yield StreamEvent(type="error", error=str(e))

    # ----- complete_with_tools --------------------------------------------

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        working_dir: str | None = None,
        max_tokens: int | None = None,
        max_turns: int = 20,
        project_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        """Run agentic tool loop via CloudCode PA with Claude model."""
        client = self._ensure_client()
        resolved = resolve_cloudcode_model(model)

        tool_handler = create_direct_handler(
            working_dir, kwargs.get("permission_config"), project_id=project_id,
        )
        session_id = str(uuid.uuid4())

        system_instruction, contents = convert_messages_for_cloudcode(messages)
        cc_tools = build_cloudcode_tools(tools)
        tool_config = build_claude_tool_config()
        thinking_level = kwargs.get("thinking_level")

        # Append thinking hint for thinking models with tools
        if is_thinking_model(resolved):
            system_instruction = append_thinking_hint(system_instruction)

        accumulated_text = ""

        try:
            for _ in range(max_turns):
                gen_config = build_claude_generation_config(
                    thinking_level=thinking_level,
                    max_tokens=max_tokens,
                    model=resolved,
                )

                data = await client.generate_content(
                    model=resolved,
                    contents=contents,
                    system_instruction=system_instruction,
                    generation_config=gen_config,
                    tools=cc_tools,
                    tool_config=tool_config,
                )

                response = data.get("response", data)
                candidates = response.get("candidates", [])

                if not candidates:
                    yield (
                        MockEvent(type="error", error="Empty response from model"),
                        session_id,
                    )
                    return

                candidate = candidates[0]
                parts = (candidate.get("content") or {}).get("parts", [])

                text_content = ""
                tool_calls: list[ToolCall] = []

                for part in parts:
                    if part.get("text") and not part.get("thought"):
                        text_content += part["text"]
                    elif part.get("functionCall"):
                        fc = part["functionCall"]
                        tool_calls.append(
                            ToolCall(
                                id=(
                                    fc.get("id")
                                    or f"{fc.get('name', 'unknown')}_{uuid.uuid4().hex[:8]}"
                                ),
                                name=fc.get("name", "unknown"),
                                input=fc.get("args", {}),
                            )
                        )

                if text_content:
                    accumulated_text += text_content
                    yield (
                        MockEvent(
                            type="assistant",
                            message=MockMessage(
                                content=[MockContentBlock(type="text", text=text_content)],
                            ),
                        ),
                        session_id,
                    )

                for tc in tool_calls:
                    yield (
                        MockEvent(
                            type="assistant",
                            message=MockMessage(
                                content=[
                                    MockContentBlock(
                                        type="tool_use", name=tc.name,
                                        input=tc.input, id=tc.id,
                                    ),
                                ],
                            ),
                        ),
                        session_id,
                    )

                if not tool_calls:
                    yield (
                        MockEvent(type="result", subtype="success", result=accumulated_text),
                        session_id,
                    )
                    return

                # Execute tools and collect results
                tool_response_parts: list[dict[str, Any]] = []
                for tc in tool_calls:
                    result = await tool_handler.execute(tc)
                    yield (
                        MockEvent(
                            type="tool_result",
                            content=result.content,
                            tool_use_id=tc.id,
                            is_error=result.is_error,
                            duration_ms=result.duration_ms,
                        ),
                        session_id,
                    )
                    tool_response_parts.append({
                        "functionResponse": {
                            "name": tc.name,
                            "id": tc.id,
                            "response": {"result": result.content},
                        },
                    })

                # Append model turn and tool results to conversation
                model_parts: list[dict[str, Any]] = []
                for part in parts:
                    if part.get("text") and not part.get("thought"):
                        model_parts.append({"text": part["text"]})
                    elif part.get("functionCall"):
                        model_parts.append({"functionCall": part["functionCall"]})
                contents.append({"role": "model", "parts": model_parts})
                contents.append({"role": "user", "parts": tool_response_parts})

            # Exhausted max_turns
            yield (
                MockEvent(type="result", subtype="success", result=accumulated_text),
                session_id,
            )

        except Exception as e:
            logger.error("CloudCode Claude tool error: %s\n%s", e, traceback.format_exc())
            yield (MockEvent(type="error", error=str(e)), session_id)

    # ----- health_check ---------------------------------------------------

    async def health_check(self) -> bool:
        """Check if CloudCode PA is reachable with Claude model."""
        try:
            client = self._ensure_client()
            resolved = resolve_cloudcode_model("cloudcode/claude-sonnet-4-6")
            data = await client.generate_content(
                model=resolved,
                contents=[{"role": "user", "parts": [{"text": "hi"}]}],
                generation_config={"maxOutputTokens": 50},
            )
            response = data.get("response", data)
            candidates = response.get("candidates", [])
            return bool(candidates)
        except Exception as e:
            logger.warning("CloudCode Claude health check failed: %s", e)
            return False
