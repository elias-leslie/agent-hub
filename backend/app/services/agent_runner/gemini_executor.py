"""Gemini tool execution handler."""

import logging
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import Message, ProviderError
from app.adapters.gemini import GeminiAdapter
from app.api.complete import complete_internal
from app.constants import GEMINI_FLASH
from app.services.memory import track_referenced_batch
from app.services.memory.citation_parser import extract_uuid_prefixes, resolve_full_uuids
from app.services.tools.base import ToolCall, ToolRegistry, ToolResult
from app.services.tools.gemini_tools import format_tools_for_api

from .debug_logging import log_agent_response, log_tool_call, log_tool_result
from .models import AgentConfig, AgentProgress, AgentResult

logger = logging.getLogger(__name__)


async def run_gemini_with_tools(
    messages: list[Message],
    config: AgentConfig,
    result: AgentResult,
    adapter: GeminiAdapter,
    progress_callback: Any | None = None,
    db: Any | None = None,
) -> AgentResult:
    """
    Run Gemini with external tool execution.

    Unlike Claude, Gemini doesn't have code execution sandbox.
    We execute tools locally using the provided ToolHandler.

    Uses complete_internal() on first turn for memory injection and session creation,
    then adapter.complete() for subsequent turns (per decision d3).
    """
    model = config.model or GEMINI_FLASH

    # Build tool registry and convert to Gemini API format
    registry = ToolRegistry(tools=config.tools or [])
    tool_defs = format_tools_for_api(registry)
    handler = config.tool_handler

    if not handler:
        raise ValueError("tool_handler required for Gemini with tools")

    # Track citations across turns (decision d4)
    all_cited_uuids: set[str] = set()
    session_id: str | None = None

    turn = 0
    while turn < config.max_turns:
        turn += 1
        result.turns = turn

        progress = AgentProgress(
            turn=turn,
            status="running",
            message=f"Turn {turn}: sending to Gemini",
        )
        result.progress_log.append(progress)
        if progress_callback:
            await progress_callback(progress)

        try:
            # First turn: use complete_internal for memory injection and session creation
            if (
                turn == 1
                and config.use_memory
                and db is not None
                and isinstance(db, AsyncSession)
            ):
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

                # Track session and citations from first turn
                session_id = internal_result.session_id
                result.session_id = session_id
                result.memory_uuids = internal_result.memory_uuids
                all_cited_uuids.update(internal_result.cited_uuids)

                # Track tokens
                result.input_tokens += internal_result.input_tokens
                result.output_tokens += internal_result.output_tokens

                content = internal_result.content
                tool_calls = internal_result.tool_calls

                # Debug log response
                log_agent_response(
                    result.agent_id, turn, content, "tool_use" if tool_calls else "end_turn"
                )
            else:
                # Subsequent turns or no memory: use adapter directly
                completion = await adapter.complete(
                    messages=messages,
                    model=model,
                    temperature=config.temperature,
                    tools=tool_defs,
                )

                # Track tokens
                result.input_tokens += completion.input_tokens
                result.output_tokens += completion.output_tokens

                content = completion.content
                tool_calls = completion.tool_calls

                # Debug log response
                log_agent_response(
                    result.agent_id, turn, content, "tool_use" if tool_calls else "end_turn"
                )

                # Extract citations from subsequent turns
                if content:
                    prefixes = extract_uuid_prefixes(content)
                    if prefixes:
                        group_id = config.memory_group_id or config.project_id
                        prefix_map = await resolve_full_uuids(prefixes, group_id)
                        all_cited_uuids.update(prefix_map.values())
                        if prefix_map:
                            await track_referenced_batch(list(prefix_map.values()))
                        logger.debug(
                            "Turn %d: extracted %d citations",
                            turn,
                            len(prefix_map),
                        )

            # Check for tool calls
            if tool_calls:
                result.tool_calls_count += len(tool_calls)

                # Execute each tool
                tool_results: list[ToolResult] = []
                for tc in tool_calls:
                    tool_call = ToolCall(
                        id=tc.id if hasattr(tc, "id") else tc.get("id", ""),
                        name=tc.name if hasattr(tc, "name") else tc.get("name", ""),
                        input=tc.input if hasattr(tc, "input") else tc.get("input", {}),
                    )

                    # Debug log tool call
                    log_tool_call(result.agent_id, turn, tool_call.name, tool_call.input)

                    progress = AgentProgress(
                        turn=turn,
                        status="tool_use",
                        message=f"Executing tool: {tool_call.name}",
                        tool_calls=[{"name": tool_call.name, "input": tool_call.input}],
                    )
                    result.progress_log.append(progress)
                    if progress_callback:
                        await progress_callback(progress)

                    # Execute via handler
                    tool_result = await handler.execute(tool_call)
                    tool_results.append(tool_result)

                    # Debug log tool result
                    log_tool_result(result.agent_id, turn, tool_call.name, tool_result.content)

                # Add assistant response with tool calls
                messages.append(Message(role="assistant", content=content))

                # Add tool results as user message
                tool_result_content = "\n".join(
                    f"Tool '{r.tool_use_id}' result: {r.content}" for r in tool_results
                )
                messages.append(
                    Message(
                        role="user",
                        content=f"Tool execution results:\n{tool_result_content}\n\nContinue based on these results.",
                    )
                )

                progress = AgentProgress(
                    turn=turn,
                    status="tool_use",
                    message=f"Executed {len(tool_results)} tool(s)",
                    tool_results=[
                        {"id": r.tool_use_id, "content": r.content[:200]} for r in tool_results
                    ],
                )
                result.progress_log.append(progress)
                if progress_callback:
                    await progress_callback(progress)

            else:
                # No tool calls - agent is done
                result.status = "success"
                result.content = content
                result.cited_uuids = list(all_cited_uuids)
                progress = AgentProgress(
                    turn=turn,
                    status="complete",
                    message="Agent completed task",
                )
                result.progress_log.append(progress)
                if progress_callback:
                    await progress_callback(progress)
                break

        except ProviderError as e:
            result.status = "error"
            result.error = str(e)
            result.cited_uuids = list(all_cited_uuids)
            break

    if result.status == "running":
        result.status = "max_turns"
        result.error = f"Reached maximum turns ({config.max_turns})"
        result.cited_uuids = list(all_cited_uuids)

    return result
