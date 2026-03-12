"""Tool handling and helpers for Claude adapter — permission checking, MCP, and SDK tool execution."""

import asyncio
import json
import logging
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import suppress
from dataclasses import asdict, dataclass
from typing import Any

from app.adapters._claude_result_metadata import (
    normalized_stop_reason,
    resolve_result_finish_reason,
)
from app.adapters.base import Message, ProviderError
from app.adapters.claude_tools_mcp import build_mcp_server as _build_mcp_server_impl
from app.adapters.claude_tools_permissions import (
    compose_permission_hooks as _compose_permission_hooks,
)
from app.adapters.claude_tools_permissions import (
    make_can_use_tool_callback as _make_can_use_tool_callback,
)
from app.adapters.claude_tools_permissions import (
    normalize_tool_name as _normalize_tool_name_impl,
)
from app.adapters.claude_utils import (
    _sdk_semaphore,
    build_sdk_options,
    extract_block_content,
    extract_system_and_conversation,
)

logger = logging.getLogger(__name__)
_SDK_POST_TOOL_IDLE_TIMEOUT_SECONDS = 300.0

# Re-export constants callers may reference
_CLI_BUILTIN_TOOLS = frozenset({"bash", "read_file", "write_file"})
_SDK_TOOL_NAME_MAP: dict[str, str] = {
    "Bash": "bash",
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "write_file",
}

_STREAM_STOP = object()  # Sentinel: async iteration exhausted


@dataclass
class ResultMessage:
    """Fallback terminal message when the Claude SDK omits its final result frame."""

    subtype: str = "success"
    duration_ms: int = 0
    duration_api_ms: int = 0
    is_error: bool = False
    num_turns: int = 0
    session_id: str | None = None
    stop_reason: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None
    structured_output: Any = None
    finish_reason: str | None = None


@dataclass
class ErrorMessage:
    """Terminal message carrying a tool-stream error without raising through the iterator."""

    error: str


async def _wrap_prompt_as_stream(prompt: str) -> Any:
    """Wrap a string prompt as an async iterable for SDK streaming callers."""

    async def _stream() -> Any:
        yield {
            "type": "user",
            "message": {"role": "user", "content": prompt},
            "parent_tool_use_id": None,
            "session_id": None,
        }

    return _stream()


def _normalize_tool_name(name: str) -> str:
    """Normalize SDK tool names for permission hooks."""
    return _normalize_tool_name_impl(name)


async def _close_sdk_message_iter(message_iter: Any) -> None:
    """Close the SDK iterator on the same task that consumed it."""
    if hasattr(message_iter, "aclose"):
        await message_iter.aclose()


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


async def _sdk_query_messages(prompt: str | AsyncIterable[dict[str, Any]], options: Any) -> AsyncIterator[Any]:
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
        from claude_agent_sdk._internal.message_parser import parse_message
        from claude_agent_sdk._internal.query import Query
        from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
    except Exception:
        from claude_agent_sdk import query as sdk_query

        async for message in sdk_query(prompt=prompt, options=options):
            yield message
        return

    transport = SubprocessCLITransport(prompt=prompt, options=options)
    query_obj: Any | None = None
    connected = False
    try:
        await transport.connect()
        connected = True

        sdk_mcp_servers = {}
        if getattr(options, "mcp_servers", None) and isinstance(options.mcp_servers, dict):
            for name, config in options.mcp_servers.items():
                if isinstance(config, dict) and config.get("type") == "sdk":
                    sdk_mcp_servers[name] = config["instance"]

        agents_dict: dict[str, dict[str, Any]] | None = None
        if getattr(options, "agents", None):
            agents_dict = {
                name: {k: v for k, v in asdict(agent_def).items() if v is not None}
                for name, agent_def in options.agents.items()
            }

        query_obj = Query(
            transport=transport,
            is_streaming_mode=True,
            can_use_tool=getattr(options, "can_use_tool", None),
            hooks=(
                _convert_hooks_to_internal_format(options.hooks)
                if getattr(options, "hooks", None)
                else None
            ),
            sdk_mcp_servers=sdk_mcp_servers,
            agents=agents_dict,
        )

        await query_obj.start()
        await query_obj.initialize()

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

        async for data in query_obj.receive_messages():
            message = parse_message(data)
            if message is not None:
                yield message
    finally:
        if query_obj is not None:
            await query_obj.close()
        elif connected:
            await transport.close()


def _build_can_use_tool(
    checker: Any | None = None,
    project_id: str | None = None,
    agent_slug: str | None = None,
) -> Any:
    """Build a can_use_tool callback with non-boundary permission layers.

    Composes hooks in order:
      1. Project permission tier (off/read/write/yolo)
      2. Cross-project path enforcement
      3. Per-request PermissionConfig (granular allow/deny via checker)

    Worktree boundary enforcement is handled separately via settings-based
    enforcement in ``_claude_settings.py`` (evaluated inside the subprocess).

    MCP tool names are normalized before passing to hooks since the SDK
    prepends 'mcp__<server>__' but hooks expect bare tool names.
    """
    return _make_can_use_tool_callback(
        _compose_permission_hooks(checker, project_id),
        agent_slug=agent_slug,
    )


def _build_mcp_server(
    tools: list[dict[str, Any]],
    working_dir: str | None,
    project_id: str | None,
    agent_slug: str | None,
    tool_catalog: list[dict[str, Any]] | None,
) -> Any | None:
    """Build an in-process SDK MCP server for custom tools."""
    return _build_mcp_server_impl(
        tools,
        working_dir,
        project_id,
        agent_slug,
        tool_catalog=tool_catalog,
    )


def _resolve_can_use_tool(
    yolo_mode: bool,
    permission_checker: Any | None,
    project_id: str | None,
    agent_slug: str | None,
) -> Any | None:
    """Return can_use_tool callback when permission hooks are needed, else None."""
    if yolo_mode and agent_slug != "persona":
        return None
    if not (permission_checker or project_id or agent_slug == "persona"):
        return None
    return _build_can_use_tool(
        checker=permission_checker,
        project_id=project_id,
        agent_slug=agent_slug,
    )


async def _next_message(message_iter: Any, idle_timeout: float | None) -> Any:
    if idle_timeout is None:
        return await anext(message_iter)
    try:
        async with asyncio.timeout(idle_timeout):
            return await anext(message_iter)
    except TimeoutError as exc:
        logger.warning("Claude SDK timed out after post-tool stall; skipping explicit iterator close")
        raise TimeoutError(f"Claude SDK stalled after tool_result for {idle_timeout:.1f}s") from exc


def _message_has_tool_use(message: Any) -> bool:
    for block in getattr(message, "content", []) or []:
        if extract_block_content(block)["type"] == "tool_use":
            return True
    return False


def _message_has_tool_result(message: Any) -> bool:
    for block in getattr(message, "content", []) or []:
        if extract_block_content(block)["type"] == "tool_result":
            return True
    return False


async def _fetch_next_or_stop(
    message_iter: Any,
    idle_timeout: float | None,
    provider_name: str,
) -> Any:
    """Fetch next message, return _STREAM_STOP on exhaustion, raise ProviderError on timeout."""
    try:
        return await _next_message(message_iter, idle_timeout)
    except StopAsyncIteration:
        return _STREAM_STOP
    except TimeoutError as exc:
        logger.error(str(exc))
        raise ProviderError(str(exc), provider=provider_name, retriable=True) from exc


async def _iterate_sdk_messages(
    prompt: str | Any,
    options: Any,
    provider_name: str,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Core message-processing loop over the claude_agent_sdk query iterator."""
    session_id: str | None = None
    done_emitted = False
    saw_payload = False
    pending_tool_calls = 0
    configured_max_turns = getattr(options, "max_turns", None)
    idle_watch_armed = False
    skip_iterator_close = False
    iterator_closed = False
    message_iter = _sdk_query_messages(prompt, options).__aiter__()
    try:
        while True:
            idle_timeout = (
                _SDK_POST_TOOL_IDLE_TIMEOUT_SECONDS
                if saw_payload and pending_tool_calls == 0 and not done_emitted
                else None
            )
            if idle_timeout is not None and not idle_watch_armed:
                logger.warning(
                    "Claude SDK post-tool idle watchdog armed: session_id=%s timeout=%.1fs",
                    session_id,
                    idle_timeout,
                )
                idle_watch_armed = True
            elif idle_timeout is None and idle_watch_armed:
                logger.info(
                    "Claude SDK post-tool idle watchdog cleared: session_id=%s pending_tool_calls=%d done=%s",
                    session_id,
                    pending_tool_calls,
                    done_emitted,
                )
                idle_watch_armed = False
            try:
                message = await _fetch_next_or_stop(message_iter, idle_timeout, provider_name)
            except ProviderError as exc:
                if "stalled after tool_result" in str(exc):
                    skip_iterator_close = True
                raise exc
            if message is _STREAM_STOP:
                if saw_payload and not done_emitted:
                    finish_reason = "end_turn"
                    logger.warning(
                        "Claude SDK stream ended without ResultMessage; synthesizing terminal result (%s)",
                        finish_reason,
                    )
                    yield (
                        ResultMessage(
                            session_id=session_id,
                            stop_reason=finish_reason,
                            finish_reason=finish_reason,
                        ),
                        session_id,
                    )
                await _close_sdk_message_iter(message_iter)
                iterator_closed = True
                return
            if hasattr(message, "subtype") and message.subtype == "init" and hasattr(message, "data"):
                session_id = message.data.get("session_id")
                if session_id:
                    logger.info(f"Claude SDK session ID: {session_id}")
                continue
            if type(message).__name__ == "ResultMessage":
                resolved_finish_reason = resolve_result_finish_reason(
                    message,
                    configured_max_turns=configured_max_turns,
                )
                resolved_stop_reason = normalized_stop_reason(
                    message,
                    configured_max_turns=configured_max_turns,
                )
                try:
                    message.finish_reason = resolved_finish_reason
                    if resolved_stop_reason is not None:
                        message.stop_reason = resolved_stop_reason
                except Exception:
                    message = ResultMessage(
                        session_id=session_id,
                        subtype=getattr(message, "subtype", "success"),
                        stop_reason=resolved_stop_reason,
                        finish_reason=resolved_finish_reason,
                        result=getattr(message, "result", None),
                        usage=getattr(message, "usage", None),
                        structured_output=getattr(message, "structured_output", None),
                        total_cost_usd=getattr(message, "total_cost_usd", None),
                        num_turns=getattr(message, "num_turns", 0),
                        is_error=getattr(message, "is_error", False),
                        duration_ms=getattr(message, "duration_ms", 0),
                        duration_api_ms=getattr(message, "duration_api_ms", 0),
                    )
                yield (message, session_id)
                done_emitted = True
                await _close_sdk_message_iter(message_iter)
                iterator_closed = True
                return
            if done_emitted:
                continue
            saw_payload = True
            if _message_has_tool_use(message):
                pending_tool_calls += 1
            if _message_has_tool_result(message):
                pending_tool_calls = max(0, pending_tool_calls - 1)
            yield (message, session_id)
    finally:
        if idle_watch_armed:
            logger.info("Claude SDK idle watchdog still armed during iterator unwind: session_id=%s", session_id)
        if skip_iterator_close:
            logger.info("Claude SDK iterator close skipped after idle-timeout unwind: session_id=%s", session_id)
        elif not iterator_closed:
            with suppress(asyncio.CancelledError):
                await _close_sdk_message_iter(message_iter)


async def _stream_sdk_messages(
    prompt: str | Any,
    options: Any,
    provider_name: str,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Yield (message, session_id) pairs from claude_agent_sdk query."""
    async with _sdk_semaphore:
        queue: asyncio.Queue[tuple[Any, str | None] | object] = asyncio.Queue()
        producer_error: str | None = None

        async def _produce() -> None:
            nonlocal producer_error
            iterator: Any = _iterate_sdk_messages(prompt, options, provider_name)
            finished_normally = False
            try:
                async for item in iterator:
                    await queue.put(item)
                finished_normally = True
            except Exception as e:
                producer_error = f"Claude tool error: {e}"
                logger.error(producer_error)
            finally:
                if not finished_normally:
                    with suppress(asyncio.CancelledError):
                        await _close_sdk_message_iter(iterator)
                await queue.put(_STREAM_STOP)

        producer_task = asyncio.create_task(_produce(), name="claude-sdk-tool-stream")
        try:
            while True:
                item = await queue.get()
                if item is _STREAM_STOP:
                    break
                yield item
            if producer_error is not None:
                yield (ErrorMessage(error=producer_error), None)
        finally:
            if not producer_task.done():
                producer_task.cancel()
            with suppress(asyncio.CancelledError):
                await producer_task


async def complete_with_tools(
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    yolo_mode: bool,
    permission_checker: Any | None,
    working_dir: str | None,
    resume_session_id: str | None,
    cli_path: str,
    model_map: dict[str, str],
    provider_name: str,
    max_turns: int | None = None,
    **kwargs: Any,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Generate with native tool calling using SDK-native permission mechanisms."""
    project_id = kwargs.get("project_id")
    agent_slug = kwargs.get("agent_slug")
    tool_catalog = kwargs.get("tool_catalog")
    # Boundary enforcement for Claude SDK is handled via settings-based
    # enforcement (settings + PreToolUse hook) — see _claude_settings.py.
    # The can_use_tool callback here is only for non-boundary permission
    # hooks (project tier, per-request checker) since the SDK subprocess
    # does not invoke can_use_tool for built-in tools.
    can_use_tool_cb = _resolve_can_use_tool(yolo_mode, permission_checker, project_id, agent_slug)
    mcp_server = _build_mcp_server(
        tools,
        working_dir,
        project_id,
        agent_slug,
        tool_catalog,
    ) if tools else None
    mcp_servers = {"agent-hub": mcp_server} if mcp_server else None

    # Build allowed_tools list including MCP tool names so Claude CLI
    # doesn't reject them (allowed_tools doesn't support wildcards).
    from app.adapters._claude_constants import build_allowed_tools

    allowed_tools = build_allowed_tools(tools) if tools else None
    system_prompt, conversation_prompt = extract_system_and_conversation(messages)
    options, use_streaming_prompt = build_sdk_options(
        cli_path=cli_path,
        model=model,
        model_map=model_map,
        working_dir=working_dir,
        yolo_mode=yolo_mode,
        can_use_tool=can_use_tool_cb,
        mcp_servers=mcp_servers,
        resume_session_id=resume_session_id,
        max_turns=max_turns,
        system_prompt=system_prompt,
        allowed_tools=allowed_tools,
        agent_slug=agent_slug,
    )
    # Working-dir sessions use settings/hooks for permission enforcement and
    # stay on plain-string prompts to avoid async-input cancel-scope corruption.
    prompt: str | Any = (
        conversation_prompt
        if working_dir
        else await _wrap_prompt_as_stream(conversation_prompt) if use_streaming_prompt else conversation_prompt
    )
    async for item in _stream_sdk_messages(prompt, options, provider_name):
        yield item
