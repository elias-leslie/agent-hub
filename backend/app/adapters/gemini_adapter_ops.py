"""Health check and complete operations for the Gemini adapter."""

import logging
from collections.abc import AsyncIterator
from typing import Any

from google.genai import types

from app.adapters.base import CompletionResult, Message
from app.adapters.gemini_cloudcode import cloudcode_tool_loop
from app.adapters.gemini_tools import execute_tool_loop
from app.adapters.gemini_utils import do_complete_call

logger = logging.getLogger(__name__)


async def sdk_health_check(client: Any) -> bool:
    """Check reachability using the GenAI SDK client."""
    from app.constants import GEMINI_FLASH

    response = await client.aio.models.generate_content(
        model=GEMINI_FLASH,
        contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
        config=types.GenerateContentConfig(max_output_tokens=50),
    )
    return response.text is not None or bool(response.candidates)


async def cloudcode_health_check(cc_client: Any) -> bool:
    """Check reachability using the CloudCode client."""
    from app.constants import GEMINI_FLASH

    data = await cc_client.generate_content(
        model=GEMINI_FLASH,
        contents=[{"role": "user", "parts": [{"text": "hi"}]}],
        generation_config={"maxOutputTokens": 50},
    )
    response = data.get("response", data)
    return bool(response.get("candidates", []))


async def sdk_complete(
    client: Any,
    messages: list[Message],
    model: str,
    temperature: float,
    max_tokens: int | None,
    provider_name: str,
    kwargs: dict[str, Any],
) -> CompletionResult:
    """Complete using the GenAI SDK with retry."""
    from app.adapters.errors import with_retry

    @with_retry
    async def _do() -> CompletionResult:
        return await do_complete_call(
            client, messages, model, temperature, max_tokens, provider_name, kwargs,
        )

    return await _do()


async def tool_loop(
    auth_mode: str,
    cc_client: Any,
    sdk_client: Any,
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    working_dir: str | None,
    max_tokens: int | None,
    max_turns: int,
    provider_name: str,
    project_id: str | None,
    kwargs: dict[str, Any],
) -> AsyncIterator[tuple[Any, str | None]]:
    """Dispatch tool loop to CloudCode or SDK path."""
    if auth_mode == "oauth" and cc_client is not None:
        async for event in cloudcode_tool_loop(
            client=cc_client,
            messages=messages,
            model=model,
            tools=tools,
            working_dir=working_dir,
            max_tokens=max_tokens,
            max_turns=max_turns,
            provider_name=provider_name,
            project_id=project_id,
            **kwargs,
        ):
            yield event
        return

    async for event in execute_tool_loop(
        client=sdk_client,
        messages=messages,
        model=model,
        tools=tools,
        working_dir=working_dir,
        max_tokens=max_tokens,
        max_turns=max_turns,
        provider_name=provider_name,
        project_id=project_id,
        **kwargs,
    ):
        yield event
