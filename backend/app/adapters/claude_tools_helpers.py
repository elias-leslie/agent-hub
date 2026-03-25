"""Tool handling and helpers for Claude adapter — permission checking, MCP, and SDK tool execution."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator
from contextlib import suppress
from dataclasses import asdict, dataclass
from typing import Any

from app.adapters._claude_result_metadata import (
    normalized_stop_reason,
    resolve_result_finish_reason,
)
from app.adapters.base import Message
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
    extract_system_and_conversation,
)
from app.adapters.runtime_session import StreamBackedRuntimeSession

logger = logging.getLogger(__name__)

# Re-export constants callers may reference
_CLI_BUILTIN_TOOLS = frozenset({"bash", "read_file", "write_file"})
_SDK_TOOL_NAME_MAP: dict[str, str] = {
    "Bash": "bash",
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "write_file",
}

_STREAM_STOP = object()  # Sentinel: async iteration exhausted


def _is_benign_interrupt_error(exc: Exception) -> bool:
    """Return True when interrupt raced with transport shutdown."""
    message = str(exc).lower()
    return (
        "not ready for writing" in message
        or "closed resource" in message
        or "broken pipe" in message
        or "connection lost" in message
    )


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


@dataclass
class _ClaudeInternalQuerySession:
    """Own one Claude SDK Query lifecycle on the task that created it."""

    prompt: str | AsyncIterable[dict[str, Any]]
    options: Any
    query_cls: Any
    parse_message: Any
    transport: Any
    query_obj: Any | None = None
    connected: bool = False
    owner_task: asyncio.Task[Any] | None = None

    async def start(self) -> None:
        """Connect transport, start Query, and send the initial prompt."""
        self.owner_task = asyncio.current_task()
        await self.transport.connect()
        self.connected = True
        self.query_obj = self.query_cls(
            transport=self.transport,
            is_streaming_mode=True,
            can_use_tool=getattr(self.options, "can_use_tool", None),
            hooks=(
                _convert_hooks_to_internal_format(self.options.hooks)
                if getattr(self.options, "hooks", None)
                else None
            ),
            sdk_mcp_servers=_extract_sdk_mcp_servers(self.options),
            agents=_extract_agents_dict(self.options),
        )
        await self.query_obj.start()
        await self.query_obj.initialize()
        await _send_prompt_to_transport(self.prompt, self.transport, self.query_obj)

    async def iter_messages(self) -> AsyncIterator[Any]:
        """Yield parsed SDK messages from the owned Query."""
        if self.query_obj is None:
            raise RuntimeError("Claude Query session was not started")
        async for data in self.query_obj.receive_messages():
            message = self.parse_message(data)
            if message is not None:
                yield message

    async def interrupt(self) -> None:
        """Interrupt the owned Query when the SDK exposes that control surface."""
        if self.query_obj is None:
            return
        interrupt = getattr(self.query_obj, "interrupt", None)
        if interrupt is None:
            return
        try:
            result = interrupt()
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            if _is_benign_interrupt_error(exc):
                logger.debug("Ignoring Claude interrupt race during transport shutdown: %s", exc)
                return
            raise

    async def close(self) -> None:
        """Close the owned Query from the correct task when possible."""
        await _close_internal_query(
            self.query_obj,
            self.transport,
            connected=self.connected,
            owner_task=self.owner_task,
        )


@dataclass
class _ClaudeSDKMessageStreamSession:
    """Own Claude SDK iterator state for one streamed tool session."""

    prompt: str | Any
    options: Any
    session_id: str | None = None
    done_emitted: bool = False
    saw_payload: bool = False
    configured_max_turns: int | None = None
    iterator_closed: bool = False

    def __post_init__(self) -> None:
        self.configured_max_turns = getattr(self.options, "max_turns", None)
        self.query_session = _ClaudeSDKQuerySession(self.prompt, self.options)

    async def _close_iterator(self) -> None:
        await self.query_session.close()
        self.iterator_closed = True

    async def interrupt(self) -> None:
        """Interrupt the active SDK query session."""
        with suppress(asyncio.CancelledError):
            await self.query_session.interrupt()

    async def close(self) -> None:
        """Close the active SDK query session once."""
        if self.iterator_closed:
            return
        await self._close_iterator()

    async def iterate(self) -> AsyncGenerator[tuple[Any, str | None]]:
        """Yield (message, session_id) pairs while owning iterator cleanup."""
        await self.query_session.start()
        message_iter = self.query_session.message_iter
        if message_iter is None:
            raise RuntimeError("Claude SDK query session did not initialize an iterator")
        try:
            while True:
                try:
                    message = await anext(message_iter)
                except StopAsyncIteration:
                    if self.saw_payload and not self.done_emitted:
                        finish_reason = "end_turn"
                        logger.warning(
                            "Claude SDK stream ended without ResultMessage; synthesizing terminal result (%s)",
                            finish_reason,
                        )
                        yield (
                            ResultMessage(
                                session_id=self.session_id,
                                stop_reason=finish_reason,
                                finish_reason=finish_reason,
                            ),
                            self.session_id,
                        )
                    await self._close_iterator()
                    return
                if hasattr(message, "subtype") and message.subtype == "init" and hasattr(message, "data"):
                    self.session_id = message.data.get("session_id")
                    if self.session_id:
                        logger.info("Claude SDK session ID: %s", self.session_id)
                    continue
                if type(message).__name__ == "ResultMessage":
                    message = _resolve_result_message(
                        message,
                        self.session_id,
                        self.configured_max_turns,
                    )
                    yield (message, self.session_id)
                    self.done_emitted = True
                    await self._close_iterator()
                    return
                if self.done_emitted:
                    continue
                self.saw_payload = True
                yield (message, self.session_id)
        finally:
            if not self.iterator_closed:
                await self.query_session.close()
                self.iterator_closed = True


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

    session = _ClaudeInternalQuerySession(
        prompt=prompt,
        options=options,
        query_cls=Query,
        parse_message=parse_message,
        transport=SubprocessCLITransport(prompt=prompt, options=options),
    )
    try:
        await session.start()
        async for message in session.iter_messages():
            yield message
    finally:
        await session.close()


@dataclass
class _ClaudeSDKQuerySession:
    """Own one Claude SDK query iterator and its cleanup lifecycle."""

    prompt: str | AsyncIterable[dict[str, Any]]
    options: Any
    internal_session: _ClaudeInternalQuerySession | None = None
    message_iter: Any | None = None
    started: bool = False
    closed: bool = False

    async def start(self) -> None:
        """Initialize the best available SDK query path once."""
        if self.started:
            return
        self.started = True
        if not all(hasattr(self.options, attr) for attr in ("cli_path", "system_prompt", "cwd")):
            from claude_agent_sdk import query as sdk_query

            self.message_iter = sdk_query(prompt=self.prompt, options=self.options).__aiter__()
            return

        try:
            from claude_agent_sdk._internal.message_parser import parse_message
            from claude_agent_sdk._internal.query import Query
            from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
        except ImportError:
            logger.debug("Claude SDK internal imports unavailable, using public query API", exc_info=True)
            from claude_agent_sdk import query as sdk_query

            self.message_iter = sdk_query(prompt=self.prompt, options=self.options).__aiter__()
            return

        try:
            self.internal_session = _ClaudeInternalQuerySession(
                prompt=self.prompt,
                options=self.options,
                query_cls=Query,
                parse_message=parse_message,
                transport=SubprocessCLITransport(prompt=self.prompt, options=self.options),
            )
            await self.internal_session.start()
            self.message_iter = self.internal_session.iter_messages().__aiter__()
        except (AttributeError, TypeError):
            logger.debug("Claude SDK internal transport unavailable for options; using public query API", exc_info=True)
            self.internal_session = None
            from claude_agent_sdk import query as sdk_query

            self.message_iter = sdk_query(prompt=self.prompt, options=self.options).__aiter__()

    async def close(self) -> None:
        """Close the iterator and owned internal session once."""
        if self.closed:
            return
        self.closed = True
        if self.message_iter is not None and hasattr(self.message_iter, "aclose"):
            with suppress(asyncio.CancelledError):
                await self.message_iter.aclose()
        if self.internal_session is not None:
            with suppress(asyncio.CancelledError):
                await self.internal_session.close()

    async def interrupt(self) -> None:
        """Interrupt the active query without forcing cross-task close semantics."""
        if self.internal_session is not None:
            with suppress(asyncio.CancelledError):
                await self.internal_session.interrupt()
            return
        if self.message_iter is None:
            return
        interrupt = getattr(self.message_iter, "interrupt", None)
        if interrupt is None:
            return
        result = interrupt()
        if asyncio.iscoroutine(result):
            with suppress(asyncio.CancelledError):
                await result


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


def _resolve_result_message(
    message: Any,
    session_id: str | None,
    configured_max_turns: int | None,
) -> Any:
    """Annotate or reconstruct a ResultMessage with resolved finish/stop reasons."""
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
        logger.debug("Failed to set finish_reason on SDK message, reconstructing", exc_info=True)
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
    return message


async def _iterate_sdk_messages(
    prompt: str | Any,
    options: Any,
    provider_name: str,
) -> AsyncGenerator[tuple[Any, str | None]]:
    """Core message-processing loop over the claude_agent_sdk query iterator."""
    del provider_name  # Reserved for future per-provider streaming specialization.
    session = _ClaudeSDKMessageStreamSession(prompt=prompt, options=options)
    session_iter = session.iterate()
    try:
        async for item in session_iter:
            yield item
    finally:
        with suppress(asyncio.CancelledError):
            await session_iter.aclose()


async def _stream_sdk_messages(
    prompt: str | Any,
    options: Any,
    provider_name: str,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Yield (message, session_id) pairs from claude_agent_sdk query.

    Iterates the SDK directly in the calling task to preserve anyio's
    task-local cancel-scope tracking.  The previous producer-task + queue
    pattern broke this invariant, causing ``CancelScope._deliver_cancellation``
    to spin at 100 % CPU when the stream was cancelled.
    """
    async with _sdk_semaphore:
        inner_iter = _iterate_sdk_messages(prompt, options, provider_name)
        exhausted = False
        try:
            async for item in inner_iter:
                yield item
            exhausted = True
        except Exception as e:
            error_msg = f"Claude tool error: {e}"
            logger.error(error_msg)
            yield (ErrorMessage(error=error_msg), None)
        finally:
            # Avoid a redundant async-generator close after natural exhaustion.
            # Claude SDK iterator unwind can inject cancellation into the current
            # task, which then corrupts downstream final response persistence.
            if not exhausted:
                await inner_iter.aclose()


async def _stream_sdk_session_messages(
    session: _ClaudeSDKMessageStreamSession,
    provider_name: str,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Yield (message, session_id) pairs from an owned SDK message session."""
    del provider_name  # Reserved for future per-provider streaming specialization.
    async with _sdk_semaphore:
        inner_iter = session.iterate()
        exhausted = False
        try:
            async for item in inner_iter:
                yield item
            exhausted = True
        except Exception as e:
            error_msg = f"Claude tool error: {e}"
            logger.error(error_msg)
            yield (ErrorMessage(error=error_msg), None)
        finally:
            if not exhausted:
                await inner_iter.aclose()


def _build_tool_infra(
    tools: list[dict[str, Any]],
    working_dir: str | None,
    project_id: str | None,
    agent_slug: str | None,
    tool_catalog: list[dict[str, Any]] | None,
    yolo_mode: bool,
    permission_checker: Any | None,
) -> tuple[Any | None, dict[str, Any] | None, list[str] | None]:
    """Build can_use_tool callback, MCP servers dict, and allowed_tools list."""
    # Boundary enforcement for Claude SDK is handled via settings-based
    # enforcement (settings + PreToolUse hook) — see _claude_settings.py.
    # The can_use_tool callback here is only for non-boundary permission
    # hooks (project tier, per-request checker) since the SDK subprocess
    # does not invoke can_use_tool for built-in tools.
    can_use_tool_cb = _resolve_can_use_tool(yolo_mode, permission_checker, project_id, agent_slug)
    mcp_server = _build_mcp_server(tools, working_dir, project_id, agent_slug, tool_catalog) if tools else None
    mcp_servers = {"agent-hub": mcp_server} if mcp_server else None

    from app.adapters._claude_constants import build_allowed_tools

    allowed_tools = build_allowed_tools(tools) if tools else None
    return can_use_tool_cb, mcp_servers, allowed_tools


async def _build_tool_message_session(
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
) -> _ClaudeSDKMessageStreamSession:
    """Build the owned Claude SDK message session for one tool turn."""
    project_id = kwargs.get("project_id")
    agent_slug = kwargs.get("agent_slug")
    tool_catalog = kwargs.get("tool_catalog")

    can_use_tool_cb, mcp_servers, allowed_tools = _build_tool_infra(
        tools, working_dir, project_id, agent_slug, tool_catalog, yolo_mode, permission_checker,
    )
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
    prompt: str | Any = (
        await _wrap_prompt_as_stream(conversation_prompt)
        if use_streaming_prompt
        else conversation_prompt
    )
    del provider_name
    return _ClaudeSDKMessageStreamSession(prompt=prompt, options=options)


async def build_tool_runtime_session(
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
) -> StreamBackedRuntimeSession:
    """Build an owned Claude runtime session with canonical ToolEvents."""
    from app.adapters.claude_tool_events import adapt_claude_stream

    sdk_session = await _build_tool_message_session(
        messages=messages,
        model=model,
        tools=tools,
        yolo_mode=yolo_mode,
        permission_checker=permission_checker,
        working_dir=working_dir,
        resume_session_id=resume_session_id,
        cli_path=cli_path,
        model_map=model_map,
        provider_name=provider_name,
        max_turns=max_turns,
        **kwargs,
    )
    return StreamBackedRuntimeSession(
        stream=adapt_claude_stream(
            _stream_sdk_session_messages(sdk_session, provider_name),
        ),
        interrupt_callback=sdk_session.interrupt,
        close_callback=sdk_session.close,
    )


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
    sdk_session = await _build_tool_message_session(
        messages=messages,
        model=model,
        tools=tools,
        yolo_mode=yolo_mode,
        permission_checker=permission_checker,
        working_dir=working_dir,
        resume_session_id=resume_session_id,
        cli_path=cli_path,
        model_map=model_map,
        provider_name=provider_name,
        max_turns=max_turns,
        **kwargs,
    )
    async for item in _stream_sdk_session_messages(sdk_session, provider_name):
        yield item
