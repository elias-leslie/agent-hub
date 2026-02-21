"""CloudCode PA client for Gemini consumer OAuth (zero per-token cost).

Uses cloudcode-pa.googleapis.com instead of Vertex AI, matching how
Gemini CLI and other consumer tools access the API with a Google
subscription (Google One AI Pro / Gemini Code Assist).

The genai SDK's vertexai=True mode routes through Vertex AI which is a
pay-per-token service and returns 404 for consumer-only models.  This
module makes raw HTTP calls to the same endpoint that the Gemini CLI uses.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.adapters.base import CompletionResult, Message, StreamEvent, ToolCallResult
from app.adapters.gemini_auth import (
    CODE_ASSIST_ENDPOINT,
)
from app.adapters.gemini_events import ToolContentBlock, ToolEvent, ToolMessage
from app.services.tools import ToolCall
from app.services.tools.direct_executor import create_direct_handler

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 300.0  # 5 minutes for agentic calls
_GENERATE_MAX_RETRIES = 3
_GENERATE_RETRY_BASE_DELAY = 2.0
_GENERATE_RETRY_MAX_DELAY = 30.0


# ---------------------------------------------------------------------------
# CloudCode HTTP client
# ---------------------------------------------------------------------------

class CloudCodeClient:
    """HTTP client for cloudcode-pa.googleapis.com consumer OAuth."""

    def __init__(
        self,
        access_token: str,
        refresh_token: str | None,
        project_id: str,
        expires_at: float | None = None,
        user_agent: str = "agent-hub",
        endpoint: str | None = None,
        extra_headers: dict[str, str | None] | None = None,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.project_id = project_id
        self.expires_at = expires_at
        self.user_agent = user_agent
        self.endpoint = endpoint or CODE_ASSIST_ENDPOINT
        self.extra_headers = extra_headers

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= (self.expires_at - 60)

    async def _ensure_token(self) -> None:
        """Refresh access token if expired, persisting to DB/cache."""
        if not self.is_expired or not self.refresh_token:
            return
        try:
            # Use the correct refresh function based on the client type
            if self.user_agent == "antigravity":
                from app.adapters.gemini_auth import refresh_antigravity_token
                creds = await refresh_antigravity_token(self.refresh_token)
            else:
                from app.adapters.gemini_auth import refresh_gemini_token
                creds = await refresh_gemini_token(self.refresh_token)

            self.access_token = creds.access_token
            self.expires_at = creds.expires_at
            if creds.refresh_token:
                self.refresh_token = creds.refresh_token
            logger.debug("CloudCode: token refreshed (agent=%s)", self.user_agent)

            # Persist the refreshed token to the credential manager
            self._persist_refreshed_token()
        except Exception:
            logger.warning("CloudCode: token refresh failed", exc_info=True)

    def _persist_refreshed_token(self) -> None:
        """Update the in-memory credential cache with the refreshed token."""
        try:
            import json

            from app.services.credential_manager import get_credential_manager

            cm = get_credential_manager()
            if not cm.is_initialized:
                return

            # Persist under the correct provider key
            provider_key = "antigravity" if self.user_agent == "antigravity" else "gemini"

            existing = cm.get(provider_key, "oauth_token")
            data = json.loads(existing) if existing else {}

            data["access_token"] = self.access_token
            data["expires_at"] = self.expires_at
            cm.set(provider_key, "oauth_token", json.dumps(data))

            if self.refresh_token:
                cm.set(provider_key, "refresh_token", self.refresh_token)

            logger.debug("CloudCode: persisted refreshed token to cache")
        except Exception:
            logger.debug("CloudCode: failed to persist token", exc_info=True)

    def _headers(self, streaming: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "User-Agent": "google-cloud-sdk vscode_cloudshelleditor/0.1",
            "X-Goog-Api-Client": "gl-node/22.17.0",
        }
        if streaming:
            headers["Accept"] = "text/event-stream"
        # Allow subclasses/callers to override headers via extra_headers.
        # A value of None means "remove this header" (e.g. to strip base
        # headers that interfere with a particular endpoint).
        if self.extra_headers:
            headers.update(self.extra_headers)
            headers = {k: v for k, v in headers.items() if v is not None}
        return headers

    def _build_request_body(
        self,
        model: str,
        contents: list[dict[str, Any]],
        system_instruction: dict[str, Any] | None = None,
        generation_config: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the cloudcode-pa request wrapper."""
        request: dict[str, Any] = {"contents": contents}
        if system_instruction:
            request["systemInstruction"] = system_instruction
        if generation_config:
            request["generationConfig"] = generation_config
        if tools:
            request["tools"] = tools
        if tool_config:
            request["toolConfig"] = tool_config

        return {
            "project": self.project_id,
            "model": model,
            "request": request,
            "requestType": "agent",
            "userAgent": self.user_agent,
            "requestId": f"agent-{uuid.uuid4()}",
        }

    async def generate_content(
        self,
        model: str,
        contents: list[dict[str, Any]],
        system_instruction: dict[str, Any] | None = None,
        generation_config: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Non-streaming generate content."""
        await self._ensure_token()
        body = self._build_request_body(
            model, contents, system_instruction, generation_config, tools,
            tool_config,
        )

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.post(
                f"{self.endpoint}/v1internal:generateContent",
                headers=self._headers(),
                json=body,
            )

        if resp.status_code != 200:
            msg = f"CloudCode generateContent HTTP {resp.status_code} (endpoint={self.endpoint}, model={model}, userAgent={self.user_agent}): {resp.text[:500]}"
            logger.error(msg)
            raise RuntimeError(msg)

        return resp.json()

    async def stream_generate_content(
        self,
        model: str,
        contents: list[dict[str, Any]],
        system_instruction: dict[str, Any] | None = None,
        generation_config: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_config: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming generate content via SSE."""
        await self._ensure_token()
        body = self._build_request_body(
            model, contents, system_instruction, generation_config, tools,
            tool_config,
        )

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_REQUEST_TIMEOUT, connect=30.0),
        ) as client, client.stream(
            "POST",
            f"{self.endpoint}/v1internal:streamGenerateContent?alt=sse",
            headers=self._headers(streaming=True),
            json=body,
        ) as resp:
            if resp.status_code != 200:
                error_text = (await resp.aread()).decode(errors="replace")
                msg = f"CloudCode stream HTTP {resp.status_code}: {error_text[:500]}"
                raise RuntimeError(msg)

            buffer = ""
            async for raw_chunk in resp.aiter_text():
                buffer += raw_chunk
                lines = buffer.split("\n")
                buffer = lines.pop()  # keep incomplete line

                for line in lines:
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    json_str = line[5:].strip()
                    if not json_str:
                        continue
                    try:
                        yield json.loads(json_str)
                    except json.JSONDecodeError:
                        logger.warning(
                            "CloudCode: bad SSE JSON: %s", json_str[:200],
                        )


# ---------------------------------------------------------------------------
# Message / tool / config conversion (Message -> raw dicts)
# ---------------------------------------------------------------------------

def convert_messages_for_cloudcode(
    messages: list[Message],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Convert Message objects to cloudcode-pa format.

    Returns:
        (system_instruction_dict | None, contents_list)
    """
    system_instruction: dict[str, Any] | None = None
    contents: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == "system":
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            system_instruction = {"parts": [{"text": text}]}
        else:
            role = "model" if msg.role == "assistant" else "user"
            parts = _build_content_parts(msg.content)
            contents.append({"role": role, "parts": parts})

    return system_instruction, contents


def _build_content_parts(
    content: str | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert content to cloudcode parts format."""
    if isinstance(content, str):
        return [{"text": content}]

    parts: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, str):
            parts.append({"text": block})
        elif isinstance(block, dict):
            block_type = block.get("type")
            if block_type == "text":
                parts.append({"text": block.get("text", "")})
            elif block_type == "image":
                source = block.get("source", {})
                if source.get("type") == "base64":
                    parts.append({
                        "inlineData": {
                            "mimeType": source.get("media_type", "image/png"),
                            "data": source.get("data", ""),
                        },
                    })
    return parts


def build_cloudcode_tools(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert tool definitions to cloudcode functionDeclarations format."""
    declarations = []
    for t in tools:
        decl: dict[str, Any] = {
            "name": t.get("name", ""),
            "description": t.get("description", ""),
        }
        schema = t.get("input_schema") or t.get("parameters")
        if schema:
            decl["parameters"] = _to_gemini_schema(schema)
        declarations.append(decl)
    return [{"functionDeclarations": declarations}]


def _to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert JSON Schema to Gemini-compatible format (uppercase types)."""
    result: dict[str, Any] = {}

    if "type" in schema:
        result["type"] = schema["type"].upper()
    if "description" in schema:
        result["description"] = schema["description"]
    if "enum" in schema:
        result["enum"] = schema["enum"]
    if "required" in schema:
        result["required"] = schema["required"]

    if "properties" in schema:
        result["properties"] = {
            k: _to_gemini_schema(v) for k, v in schema["properties"].items()
        }

    if "items" in schema:
        result["items"] = _to_gemini_schema(schema["items"])

    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            result[key] = [_to_gemini_schema(s) for s in schema[key]]

    return result


def build_generation_config(
    temperature: float = 1.0,
    max_tokens: int | None = None,
    model: str = "",
    thinking_level: str | None = None,
) -> dict[str, Any] | None:
    """Build generationConfig for cloudcode-pa requests."""
    config: dict[str, Any] = {}

    if temperature != 1.0:
        config["temperature"] = temperature
    if max_tokens is not None:
        config["maxOutputTokens"] = max_tokens

    # Thinking config for Gemini 3 models
    if thinking_level and "gemini-3" in model:
        from app.adapters.gemini_thinking import (
            THINKING_LEVEL_MAP_FLASH,
            THINKING_LEVEL_MAP_PRO,
        )

        is_pro = "pro" in model.lower()
        level_map = THINKING_LEVEL_MAP_PRO if is_pro else THINKING_LEVEL_MAP_FLASH
        level = level_map.get(thinking_level, "high")
        config["thinkingConfig"] = {
            "includeThoughts": True,
            "thinkingLevel": level.upper(),
        }

    return config if config else None


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def parse_cloudcode_response(
    data: dict[str, Any],
    model: str,
    provider_name: str,
) -> CompletionResult:
    """Parse cloudcode-pa response into CompletionResult."""
    response = data.get("response", data)  # unwrap if wrapped

    candidates = response.get("candidates", [])
    content = ""
    thinking_content = ""
    tool_calls: list[ToolCallResult] = []
    finish_reason = None

    if candidates:
        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        parts = (candidate.get("content") or {}).get("parts", [])

        for part in parts:
            if part.get("thought") and part.get("text"):
                thinking_content += part["text"]
            elif part.get("text"):
                content += part["text"]
            elif part.get("functionCall"):
                fc = part["functionCall"]
                tool_calls.append(
                    ToolCallResult(
                        id=fc.get("id") or fc.get("name", "unknown"),
                        name=fc.get("name", "unknown"),
                        input=fc.get("args", {}),
                    )
                )

    usage = response.get("usageMetadata", {})
    input_tokens = usage.get("promptTokenCount", 0) or 0
    output_tokens = usage.get("candidatesTokenCount", 0) or 0
    thoughts_token_count = usage.get("thoughtsTokenCount")

    thinking_tokens = thoughts_token_count or (
        len(thinking_content) // 4 if thinking_content else None
    )

    return CompletionResult(
        content=content,
        model=model,
        provider=provider_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=finish_reason,
        raw_response=data,
        tool_calls=tool_calls if tool_calls else None,
        thinking_content=thinking_content if thinking_content else None,
        thinking_tokens=thinking_tokens,
    )


# ---------------------------------------------------------------------------
# High-level operations (complete / stream / tool loop)
# ---------------------------------------------------------------------------

async def cloudcode_complete(
    client: CloudCodeClient,
    messages: list[Message],
    model: str,
    temperature: float = 1.0,
    max_tokens: int | None = None,
    provider_name: str = "gemini",
    kwargs: dict[str, Any] | None = None,
) -> CompletionResult:
    """Non-streaming completion via cloudcode-pa."""
    kwargs = kwargs or {}
    system_instruction, contents = convert_messages_for_cloudcode(messages)
    generation_config = build_generation_config(
        temperature, max_tokens, model, kwargs.get("thinking_level"),
    )
    tools = (
        build_cloudcode_tools(kwargs["tools"]) if kwargs.get("tools") else None
    )

    data = await client.generate_content(
        model=model,
        contents=contents,
        system_instruction=system_instruction,
        generation_config=generation_config,
        tools=tools,
    )
    return parse_cloudcode_response(data, model, provider_name)


async def cloudcode_stream(
    client: CloudCodeClient,
    messages: list[Message],
    model: str,
    temperature: float = 1.0,
    max_tokens: int | None = None,
    provider_name: str = "gemini",
    kwargs: dict[str, Any] | None = None,
) -> AsyncIterator[StreamEvent]:
    """Stream completion via cloudcode-pa SSE."""
    kwargs = kwargs or {}
    system_instruction, contents = convert_messages_for_cloudcode(messages)
    generation_config = build_generation_config(
        temperature, max_tokens, model, kwargs.get("thinking_level"),
    )
    tools = (
        build_cloudcode_tools(kwargs["tools"]) if kwargs.get("tools") else None
    )

    total_content = ""
    input_tokens = 0
    output_tokens = 0
    finish_reason = "STOP"

    try:
        async for chunk in client.stream_generate_content(
            model=model,
            contents=contents,
            system_instruction=system_instruction,
            generation_config=generation_config,
            tools=tools,
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

            # Update usage from each chunk (last one wins)
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
        logger.error("CloudCode stream error: %s", e)
        yield StreamEvent(type="error", error=str(e))


async def cloudcode_tool_loop(
    client: CloudCodeClient,
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    working_dir: str | None,
    max_tokens: int | None,
    max_turns: int,
    provider_name: str,
    permission_config: dict[str, Any] | None = None,
    project_id: str | None = None,
    **kwargs: Any,
) -> AsyncIterator[tuple[ToolEvent, str]]:
    """Run agentic tool loop via cloudcode-pa."""
    tool_handler = create_direct_handler(
        working_dir, permission_config, project_id=project_id,
    )
    session_id = str(uuid.uuid4())

    system_instruction, contents = convert_messages_for_cloudcode(messages)
    cc_tools = build_cloudcode_tools(tools)
    thinking_level = kwargs.get("thinking_level")

    accumulated_text = ""

    try:
        for _ in range(max_turns):
            gen_config = build_generation_config(
                1.0, max_tokens, model, thinking_level,
            )

            data = await _generate_with_retry(
                client, model, contents, system_instruction, gen_config, cc_tools,
            )

            response = data.get("response", data)
            candidates = response.get("candidates", [])

            if not candidates:
                yield (
                    ToolEvent(type="error", error="Empty response from model"),
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
                    ToolEvent(
                        type="assistant",
                        message=ToolMessage(
                            content=[ToolContentBlock(type="text", text=text_content)],
                        ),
                    ),
                    session_id,
                )

            for tc in tool_calls:
                yield (
                    ToolEvent(
                        type="assistant",
                        message=ToolMessage(
                            content=[
                                ToolContentBlock(
                                    type="tool_use",
                                    name=tc.name,
                                    input=tc.input,
                                    id=tc.id,
                                ),
                            ],
                        ),
                    ),
                    session_id,
                )

            if not tool_calls:
                yield (
                    ToolEvent(
                        type="result", subtype="success", result=accumulated_text,
                    ),
                    session_id,
                )
                return

            # Execute tools and collect results
            tool_response_parts: list[dict[str, Any]] = []
            for tc in tool_calls:
                result = await tool_handler.execute(tc)
                yield (
                    ToolEvent(
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
            # Preserve thoughtSignature on functionCall/thought parts (required by CloudCode PA API
            # when thinking is enabled — see https://docs.cloud.google.com/vertex-ai/generative-ai/docs/thought-signatures)
            model_parts: list[dict[str, Any]] = []
            for part in parts:
                if part.get("text") and not part.get("thought"):
                    model_parts.append({"text": part["text"]})
                elif part.get("thought") and part.get("text"):
                    thought_part: dict[str, Any] = {"text": part["text"], "thought": True}
                    if part.get("thoughtSignature"):
                        thought_part["thoughtSignature"] = part["thoughtSignature"]
                    model_parts.append(thought_part)
                elif part.get("functionCall"):
                    fc_part: dict[str, Any] = {"functionCall": part["functionCall"]}
                    if part.get("thoughtSignature"):
                        fc_part["thoughtSignature"] = part["thoughtSignature"]
                    model_parts.append(fc_part)
            contents.append({"role": "model", "parts": model_parts})
            contents.append({"role": "user", "parts": tool_response_parts})

        # Exhausted max_turns
        yield (
            ToolEvent(type="result", subtype="success", result=accumulated_text),
            session_id,
        )

    except Exception as e:
        logger.error("CloudCode tool error: %s\n%s", e, traceback.format_exc())
        yield (ToolEvent(type="error", error=str(e)), session_id)


# ---------------------------------------------------------------------------
# Internal retry helper
# ---------------------------------------------------------------------------

def _is_retryable_status(status_code: int) -> bool:
    return status_code in {429, 500, 502, 503, 504}


def _is_retryable_error(text: str) -> bool:
    lower = text.lower()
    return any(
        kw in lower
        for kw in (
            "resource exhausted",
            "rate limit",
            "overloaded",
            "service unavailable",
            "deadline_exceeded",
        )
    )


async def _generate_with_retry(
    client: CloudCodeClient,
    model: str,
    contents: list[dict[str, Any]],
    system_instruction: dict[str, Any] | None,
    generation_config: dict[str, Any] | None,
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Call generate_content with retry on transient errors."""
    import asyncio

    last_exc: Exception | None = None
    for attempt in range(_GENERATE_MAX_RETRIES):
        try:
            return await client.generate_content(
                model=model,
                contents=contents,
                system_instruction=system_instruction,
                generation_config=generation_config,
                tools=tools,
            )
        except RuntimeError as e:
            error_str = str(e)
            if not _is_retryable_error(error_str):
                raise
            last_exc = e
        except httpx.HTTPStatusError as e:
            if not _is_retryable_status(e.response.status_code):
                raise
            last_exc = e
        except (httpx.ConnectError, httpx.ReadTimeout) as e:
            last_exc = e

        delay = min(
            _GENERATE_RETRY_BASE_DELAY * (2**attempt), _GENERATE_RETRY_MAX_DELAY,
        )
        logger.warning(
            "CloudCode retry %d/%d after %s (delay=%.1fs)",
            attempt + 1,
            _GENERATE_MAX_RETRIES,
            type(last_exc).__name__,
            delay,
        )
        await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]
