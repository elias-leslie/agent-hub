"""Gemini tool execution handler."""

import logging
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import Message, ProviderError
from app.adapters.gemini import GeminiAdapter
from app.api.complete import complete_internal
from app.constants import GEMINI_FLASH
from app.services.tools.base import ToolRegistry
from app.services.tools.gemini_tools import format_tools_for_api

from .debug_logging import log_agent_response, log_tool_call, log_tool_result
from .executor_utils import (
    append_tool_messages,
    emit_progress,
    execute_tools_gemini,
    extract_and_track_citations,
    track_tokens,
)
from .models import AgentConfig, AgentResult

logger = logging.getLogger(__name__)


async def run_gemini_with_tools(
    messages: list[Message],
    config: AgentConfig,
    result: AgentResult,
    adapter: GeminiAdapter,
    progress_callback: Any | None = None,
    db: Any | None = None,
) -> AgentResult:
    """Run Gemini with external tool execution.

    Uses complete_internal() on first turn for memory injection,
    then adapter.complete() for subsequent turns.
    """
    model = config.model or GEMINI_FLASH
    registry = ToolRegistry(tools=config.tools or [])
    tool_defs = format_tools_for_api(registry)
    handler = config.tool_handler
    if not handler:
        raise ValueError("tool_handler required for Gemini with tools")
    all_cited_uuids: set[str] = set()
    session_id: str | None = None

    turn = 0
    while turn < config.max_turns:
        turn += 1
        result.turns = turn
        await emit_progress(
            result, turn, "running", f"Turn {turn}: sending to Gemini", progress_callback
        )

        try:
            # First turn: use complete_internal for memory injection and session creation
            if turn == 1 and config.use_memory and db is not None and isinstance(db, AsyncSession):
                messages_dict = [{"role": m.role, "content": m.content} for m in messages]
                internal_result = await complete_internal(
                    messages=messages_dict,
                    model=model,
                    provider="gemini",
                    temperature=config.temperature,
                    project_id=config.project_id,
                    db=db,
                    session_id=session_id,
                    agent_slug=config.agent_slug,
                    use_memory=config.use_memory,
                    memory_group_id=config.memory_group_id,
                    tools=cast(list[dict[str, Any]], tool_defs),
                    skip_cache=True,
                )

                session_id = result.session_id = internal_result.session_id
                result.memory_uuids = internal_result.memory_uuids
                all_cited_uuids.update(internal_result.cited_uuids)
                track_tokens(result, internal_result.input_tokens, internal_result.output_tokens)
                content, tool_calls = internal_result.content, internal_result.tool_calls
                log_agent_response(
                    result.agent_id, turn, content, "tool_use" if tool_calls else "end_turn"
                )
            else:
                completion = await adapter.complete(
                    messages=messages, model=model, temperature=config.temperature, tools=tool_defs
                )
                track_tokens(result, completion.input_tokens, completion.output_tokens)
                content, tool_calls = completion.content, completion.tool_calls
                log_agent_response(
                    result.agent_id, turn, content, "tool_use" if tool_calls else "end_turn"
                )
                if content:
                    cited = await extract_and_track_citations(
                        content, config.memory_group_id or config.project_id, turn
                    )
                    all_cited_uuids.update(cited)

            if tool_calls:
                result.tool_calls_count += len(tool_calls)
                tool_results = await execute_tools_gemini(
                    tool_calls,
                    handler,
                    result,
                    turn,
                    progress_callback,
                    log_tool_call,
                    log_tool_result,
                )
                append_tool_messages(messages, content, tool_results)
                await emit_progress(
                    result,
                    turn,
                    "tool_use",
                    f"Executed {len(tool_results)} tool(s)",
                    progress_callback,
                    tool_results=[
                        {"id": r.tool_use_id, "content": r.content[:200]} for r in tool_results
                    ],
                )
            else:
                result.status = "success"
                result.content = content
                result.cited_uuids = list(all_cited_uuids)
                await emit_progress(
                    result, turn, "complete", "Agent completed task", progress_callback
                )
                break

        except ProviderError as e:
            result.status, result.error, result.cited_uuids = "error", str(e), list(all_cited_uuids)
            break
    if result.status == "running":
        result.status, result.error, result.cited_uuids = (
            "max_turns",
            f"Reached maximum turns ({config.max_turns})",
            list(all_cited_uuids),
        )
    return result
