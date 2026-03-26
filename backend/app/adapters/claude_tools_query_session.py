"""Low-level Claude SDK query session classes and transport helpers."""

import asyncio
import json
import logging
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import suppress
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)


def _is_benign_interrupt_error(exc: Exception) -> bool:
    """Return True when interrupt raced with transport shutdown."""
    message = str(exc).lower()
    return (
        "not ready for writing" in message
        or "closed resource" in message
        or "broken pipe" in message
        or "connection lost" in message
    )


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
class _ClaudeSDKQuerySession:
    """Own one Claude SDK query iterator and its cleanup lifecycle."""

    prompt: str | AsyncIterable[dict[str, Any]]
    options: Any
    internal_session: _ClaudeInternalQuerySession | None = None
    message_iter: Any | None = None
    started: bool = False
    closed: bool = False

    def _use_public_query_api(self) -> None:
        from claude_agent_sdk import query as sdk_query

        self.message_iter = sdk_query(prompt=self.prompt, options=self.options).__aiter__()

    async def _try_start_internal_session(
        self, Query: Any, parse_message: Any, SubprocessCLITransport: Any
    ) -> bool:
        """Try to start an internal SDK session; return True on success."""
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
            return True
        except (AttributeError, TypeError):
            logger.debug("Claude SDK internal transport unavailable; using public query API", exc_info=True)
            self.internal_session = None
            return False

    async def start(self) -> None:
        """Initialize the best available SDK query path once."""
        if self.started:
            return
        self.started = True
        if not all(hasattr(self.options, attr) for attr in ("cli_path", "system_prompt", "cwd")):
            self._use_public_query_api()
            return
        try:
            from claude_agent_sdk._internal.message_parser import parse_message
            from claude_agent_sdk._internal.query import Query
            from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
        except ImportError:
            logger.debug("Claude SDK internal imports unavailable, using public query API", exc_info=True)
            self._use_public_query_api()
            return
        if not await self._try_start_internal_session(Query, parse_message, SubprocessCLITransport):
            self._use_public_query_api()

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
