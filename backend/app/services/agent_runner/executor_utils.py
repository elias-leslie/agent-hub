"""Shared utilities for executor implementations."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, cast

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters.base import Message, ToolCallIdNormalizer
from app.config import settings
from app.models import Session
from app.services.memory import track_referenced_batch
from app.services.memory.citation_parser import extract_uuid_prefixes, resolve_full_uuids
from app.services.message_transform import Provider, transform_messages
from app.services.tools.base import ToolCall, ToolDecision, ToolResult

from .models import AgentProgress, AgentResult

logger = logging.getLogger(__name__)

# Redis clients for real-time event publishing
_redis_client: aioredis.Redis[bytes] | None = None
_summitflow_redis_client: aioredis.Redis[bytes] | None = None

# SummitFlow Redis URL (db 0) for WebSocket events
SUMMITFLOW_REDIS_URL = "redis://localhost:6379/0"


async def _get_redis() -> aioredis.Redis[bytes]:
    """Get or create async Redis client for Agent Hub events (db 2)."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.agent_hub_redis_url)
    return _redis_client


async def _get_summitflow_redis() -> aioredis.Redis[bytes]:
    """Get or create async Redis client for SummitFlow WebSocket events (db 0)."""
    global _summitflow_redis_client
    if _summitflow_redis_client is None:
        _summitflow_redis_client = aioredis.from_url(SUMMITFLOW_REDIS_URL)
    return _summitflow_redis_client


async def publish_agent_event(
    project_id: str,
    trace_id: str,
    event_type: str,
    message: str,
    *,
    tool_name: str | None = None,
    tool_input: dict[str, Any] | None = None,
    tool_result: str | None = None,
    is_error: bool = False,
) -> None:
    """Publish agent event to Redis for real-time observability.

    Events are published to:
    1. 'agent:events:{project_id}' - for Agent Hub subscribers
    2. 'ws:execution:{trace_id}' - for SummitFlow WebSocket (if trace_id is a task_id)
    3. Stored in list 'agent:events:{trace_id}' for CLI retrieval
    """
    try:
        r = await _get_redis()
        timestamp = datetime.now(UTC).isoformat()

        # Agent Hub event format
        event = {
            "timestamp": timestamp,
            "project_id": project_id,
            "trace_id": trace_id,
            "event_type": event_type,
            "message": message,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_result": tool_result[:500] if tool_result else None,
            "is_error": is_error,
        }
        event_json = json.dumps(event)

        # Publish for Agent Hub subscribers
        await r.publish(f"agent:events:{project_id}", event_json)

        # Also publish in SummitFlow WebSocket format if trace_id looks like a task_id
        # Uses SummitFlow's Redis (db 0) so WebSocket subscribers receive events
        if trace_id and trace_id.startswith("task-"):
            ws_event = {
                "type": "log",
                "data": {
                    "level": "error" if is_error else "info",
                    "message": f"[agent] {tool_name}: {message}"
                    if tool_name
                    else f"[agent] {message}",
                    "source": "agent",
                    "tool_name": tool_name,
                },
            }
            sf_redis = await _get_summitflow_redis()
            await sf_redis.publish(f"ws:execution:{trace_id}", json.dumps(ws_event))

        # Store in list for CLI retrieval (with 1 hour TTL)
        list_key = f"agent:events:{trace_id}"
        await r.rpush(list_key, event_json)
        await r.expire(list_key, 3600)

    except Exception as e:
        # Don't fail agent execution if Redis publish fails
        logger.warning(f"Failed to publish agent event: {e}")


async def load_session_history(
    db: AsyncSession,
    session_id: str,
    target_provider: Provider | None = None,
) -> tuple[list[Message], str | None]:
    """Load conversation history from a session for continuation.

    Args:
        db: Database session
        session_id: Session ID to load history from
        target_provider: If provided, transform messages for this target provider.
            This handles cross-provider failover (thinking blocks, tool IDs, etc.)

    Returns:
        Tuple of (messages list, provider_metadata's sdk_session_id if any)

    Raises:
        ValueError: If session not found
    """
    result = await db.execute(
        select(Session).options(selectinload(Session.messages)).where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()

    if not session:
        raise ValueError(f"Session {session_id} not found for continuation")

    # Convert DB messages to Message objects
    messages: list[Message] = []
    for m in sorted(session.messages, key=lambda x: x.created_at):
        messages.append(Message(role=m.role, content=m.content))

    # Extract SDK session ID from provider_metadata (for Claude resume)
    sdk_session_id: str | None = None
    if session.provider_metadata:
        sdk_session_id = session.provider_metadata.get("sdk_session_id")

    # Apply cross-provider transformation if target differs from source
    raw_provider = session.provider or "claude"
    source_provider = cast(
        Provider,
        raw_provider if raw_provider in ("claude", "anthropic", "gemini", "openai") else "claude",
    )
    if target_provider and target_provider != source_provider:
        transform_result = transform_messages(
            messages,
            source_provider,
            target_provider,
            normalize_tool_ids=True,
        )
        messages = transform_result.messages
        logger.info(
            f"Transformed {len(messages)} messages for {source_provider} -> {target_provider}: "
            f"thinking={transform_result.thinking_converted}, "
            f"tool_ids={transform_result.tool_ids_normalized}, "
            f"orphaned={transform_result.orphaned_resolved}"
        )

    logger.info(
        f"Loaded {len(messages)} messages from session {session_id} "
        f"(sdk_session_id={sdk_session_id})"
    )

    return messages, sdk_session_id


async def save_sdk_session_id(
    db: AsyncSession,
    session_id: str,
    sdk_session_id: str,
) -> None:
    """Save SDK session ID to provider_metadata for later resume.

    Args:
        db: Database session
        session_id: Our session ID
        sdk_session_id: SDK's session ID (e.g., Claude Agent SDK session UUID)
    """
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        logger.warning(f"Session {session_id} not found for SDK session save")
        return

    if session.provider_metadata is None:
        session.provider_metadata = {}

    session.provider_metadata["sdk_session_id"] = sdk_session_id
    await db.commit()
    logger.info(f"Saved SDK session ID {sdk_session_id} to session {session_id}")


async def emit_progress(
    result: AgentResult,
    turn: int,
    status: str,
    message: str,
    callback: Any | None = None,
    *,
    project_id: str | None = None,
    trace_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Create progress entry, invoke callback, and publish to Redis for real-time observability."""
    progress = AgentProgress(turn=turn, status=status, message=message, **kwargs)
    result.progress_log.append(progress)

    # Publish to Redis for real-time observability
    if project_id and trace_id:
        tool_calls = kwargs.get("tool_calls", [])
        tool_results = kwargs.get("tool_results", [])

        # Publish each tool call as a separate event
        for tc in tool_calls:
            tool_name = (
                tc.get("name", "unknown")
                if isinstance(tc, dict)
                else getattr(tc, "name", "unknown")
            )
            tool_input = tc.get("input", {}) if isinstance(tc, dict) else getattr(tc, "input", {})
            await publish_agent_event(
                project_id=project_id,
                trace_id=trace_id,
                event_type="tool_call",
                message=f"Tool: {tool_name}",
                tool_name=tool_name,
                tool_input=tool_input,
            )

        # Publish tool results
        for tr in tool_results:
            content = tr.get("content", "") if isinstance(tr, dict) else getattr(tr, "content", "")
            is_error = (
                tr.get("is_error", False)
                if isinstance(tr, dict)
                else getattr(tr, "is_error", False)
            )
            await publish_agent_event(
                project_id=project_id,
                trace_id=trace_id,
                event_type="tool_result",
                message=content[:200] if content else "",
                tool_result=content,
                is_error=is_error,
            )

        # Publish status messages
        if not tool_calls and not tool_results:
            await publish_agent_event(
                project_id=project_id,
                trace_id=trace_id,
                event_type=status,
                message=message,
            )

    if callback:
        await callback(progress)


def track_tokens(result: AgentResult, input_tokens: int, output_tokens: int) -> None:
    """Add tokens to result totals."""
    result.input_tokens += input_tokens
    result.output_tokens += output_tokens


async def extract_and_track_citations(content: str, group_id: str, turn: int) -> set[str]:
    """Extract UUID citations from content and track them."""
    cited_uuids: set[str] = set()
    prefixes = extract_uuid_prefixes(content)
    if prefixes:
        prefix_map = await resolve_full_uuids(prefixes, group_id)
        cited_uuids.update(prefix_map.values())
        if prefix_map:
            await track_referenced_batch(list(prefix_map.values()))
        logger.debug("Turn %d: extracted %d citations", turn, len(prefix_map))
    return cited_uuids


def build_tool_call(tc: Any, target_provider: str = "anthropic") -> ToolCall:
    """Extract ToolCall from various formats with ID normalization.

    Args:
        tc: Tool call object (can be object with attributes or dict)
        target_provider: Target provider for ID normalization ("anthropic", "gemini", etc.)

    Returns:
        ToolCall with normalized ID (original preserved in original_id if changed)
    """
    original_id = tc.id if hasattr(tc, "id") else tc.get("id", "")
    name = tc.name if hasattr(tc, "name") else tc.get("name", "")
    tool_input = tc.input if hasattr(tc, "input") else tc.get("input", {})

    normalized_id, kept_original = ToolCallIdNormalizer.normalize(original_id, target_provider)

    if kept_original:
        logger.debug(
            f"Normalized tool call ID from {len(original_id)} chars to {len(normalized_id)} chars"
        )

    return ToolCall(
        id=normalized_id,
        name=name,
        input=tool_input,
        original_id=kept_original,
    )


def append_tool_messages(
    messages: list[Message], content: str, tool_results: list[ToolResult]
) -> None:
    """Append assistant and tool result messages to conversation."""
    messages.append(Message(role="assistant", content=content))
    tool_result_content = "\n".join(
        f"Tool '{r.tool_use_id}' result: {r.content}" for r in tool_results
    )
    messages.append(
        Message(
            role="user",
            content=f"Tool execution results:\n{tool_result_content}\n\nContinue based on these results.",
        )
    )


async def execute_tools_gemini(
    tool_calls: list[Any],
    handler: Any,
    result: AgentResult,
    turn: int,
    progress_callback: Any | None,
    log_tool_call_fn: Any,
    log_tool_result_fn: Any,
) -> list[ToolResult]:
    """Execute tool calls and return results.

    Checks permissions before executing each tool. Denied tools return
    an error result instead of executing.
    """
    tool_results: list[ToolResult] = []
    for tc in tool_calls:
        tool_call = build_tool_call(tc, target_provider="gemini")
        log_tool_call_fn(result.agent_id, turn, tool_call.name, tool_call.input)

        await emit_progress(
            result,
            turn,
            "tool_use",
            f"Executing tool: {tool_call.name}",
            progress_callback,
            tool_calls=[{"name": tool_call.name, "input": tool_call.input}],
        )

        # Check permission before execution
        decision = await handler.check_permission(tool_call)

        if decision == ToolDecision.DENY:
            tool_result = ToolResult(
                tool_use_id=tool_call.id,
                content=f"Permission denied: tool '{tool_call.name}' is not allowed",
                is_error=True,
            )
            logger.warning(f"Tool permission denied: {tool_call.name}")
        elif decision == ToolDecision.ASK:
            # In autonomous mode, ASK is treated as DENY (no user to confirm)
            tool_result = ToolResult(
                tool_use_id=tool_call.id,
                content=f"Permission required: tool '{tool_call.name}' requires confirmation (not available in autonomous mode)",
                is_error=True,
            )
            logger.warning(f"Tool requires confirmation (denied in autonomous): {tool_call.name}")
        else:
            # ALLOW - execute the tool
            tool_result = await handler.execute(tool_call)

        tool_results.append(tool_result)
        log_tool_result_fn(result.agent_id, turn, tool_call.name, tool_result.content)

    return tool_results
