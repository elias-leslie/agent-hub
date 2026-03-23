"""Claude SDK transport and internal Query API infrastructure.

Owns the subprocess CLI transport lifecycle, Query initialization,
and raw message iteration — everything below the message-processing loop.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import suppress
from dataclasses import asdict
from typing import Any

logger = logging.getLogger(__name__)


async def _close_sdk_message_iter(message_iter: Any) -> None:
    """Close the SDK iterator on the same task that consumed it."""
    if hasattr(message_iter, "aclose"):
        await message_iter.aclose()


async def _close_internal_query(
    query_obj: Any | None,
    transport: Any,
    *,
    connected: bool,
    owner_task: asyncio.Task[Any] | None,
) -> None:
    """Close the Claude SDK query only from its owner task.

    The SDK's internal Query owns an anyio cancel scope that must be exited
    from the same task that entered it. Async-generator shutdown can run from a
    different task during cancellation, so we skip Query.close() in that case
    and fall back to best-effort transport shutdown instead.
    """
    if query_obj is None:
        if connected and hasattr(transport, "close"):
            await transport.close()
        return

    current_task = asyncio.current_task()
    if owner_task is None or current_task is owner_task:
        await query_obj.close()
        return

    logger.warning(
        "Skipping Claude Query.close() from foreign task: owner=%s current=%s",
        owner_task,
        current_task,
    )
    if connected and hasattr(transport, "close"):
        with suppress(Exception):
            await transport.close()


def _convert_hooks_to_internal_format(hooks: dict[str, list[Any]]) -> dict[str, list[dict[str, Any]]]:
    """Convert HookMatcher structures to the SDK Query internal format."""
    internal_hooks: dict[str, list[dict[str, Any]]] = {}
    for event, matchers in hooks.items():
        internal_hooks[event] = []
        for matcher in matchers:
            internal_matcher: dict[str, Any] = {
                "matcher": matcher.matcher if hasattr(matcher, "matcher") else None,
                "hooks": matcher.hooks if hasattr(matcher, "hooks") else [],
            }
            if hasattr(matcher, "timeout") and matcher.timeout is not None:
                internal_matcher["timeout"] = matcher.timeout
            internal_hooks[event].append(internal_matcher)
    return internal_hooks


def _extract_sdk_mcp_servers(options: Any) -> dict[str, Any]:
    """Extract SDK-type MCP server instances from options."""
    sdk_mcp_servers: dict[str, Any] = {}
    if getattr(options, "mcp_servers", None) and isinstance(options.mcp_servers, dict):
        for name, config in options.mcp_servers.items():
            if isinstance(config, dict) and config.get("type") == "sdk":
                sdk_mcp_servers[name] = config["instance"]
    return sdk_mcp_servers


def _extract_agents_dict(options: Any) -> dict[str, dict[str, Any]] | None:
    """Convert options.agents to plain dicts, dropping None values."""
    if not getattr(options, "agents", None):
        return None
    return {
        name: {k: v for k, v in asdict(agent_def).items() if v is not None}
        for name, agent_def in options.agents.items()
    }


async def _send_prompt_to_transport(
    prompt: str | AsyncIterable[dict[str, Any]],
    transport: Any,
    query_obj: Any,
) -> None:
    """Write prompt into the transport or start streaming input on the query."""
    if isinstance(prompt, str):
        user_message = {
            "type": "user",
            "session_id": "",
            "message": {"role": "user", "content": prompt},
            "parent_tool_use_id": None,
        }
        await transport.write(json.dumps(user_message) + "\n")
        await transport.end_input()
    elif isinstance(prompt, AsyncIterable) and query_obj._tg:
        query_obj._tg.start_soon(query_obj.stream_input, prompt)


async def _sdk_query_via_internal_api(
    prompt: str | AsyncIterable[dict[str, Any]],
    options: Any,
) -> AsyncIterator[Any]:
    """Yield parsed messages using the Claude SDK internal Query API."""
    from claude_agent_sdk._internal.message_parser import parse_message
    from claude_agent_sdk._internal.query import Query
    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

    transport = SubprocessCLITransport(prompt=prompt, options=options)
    query_obj: Any | None = None
    connected = False
    owner_task = asyncio.current_task()
    try:
        await transport.connect()
        connected = True

        query_obj = Query(
            transport=transport,
            is_streaming_mode=True,
            can_use_tool=getattr(options, "can_use_tool", None),
            hooks=(
                _convert_hooks_to_internal_format(options.hooks)
                if getattr(options, "hooks", None)
                else None
            ),
            sdk_mcp_servers=_extract_sdk_mcp_servers(options),
            agents=_extract_agents_dict(options),
        )

        await query_obj.start()
        await query_obj.initialize()
        await _send_prompt_to_transport(prompt, transport, query_obj)

        async for data in query_obj.receive_messages():
            message = parse_message(data)
            if message is not None:
                yield message
    finally:
        await _close_internal_query(
            query_obj,
            transport,
            connected=connected,
            owner_task=owner_task,
        )


async def _sdk_query_messages(
    prompt: str | AsyncIterable[dict[str, Any]],
    options: Any,
) -> AsyncIterator[Any]:
    """Yield parsed Claude SDK messages while owning Query lifecycle in this task."""
    if not hasattr(options, "cli_path") or not hasattr(options, "system_prompt"):
        from claude_agent_sdk import query as sdk_query

        message_iter = sdk_query(prompt=prompt, options=options).__aiter__()
        try:
            async for message in message_iter:
                yield message
        finally:
            await _close_sdk_message_iter(message_iter)
        return

    try:
        async for message in _sdk_query_via_internal_api(prompt, options):
            yield message
    except ImportError:
        logger.debug("Claude SDK internal imports unavailable, using public query API", exc_info=True)
        from claude_agent_sdk import query as sdk_query

        async for message in sdk_query(prompt=prompt, options=options):
            yield message
