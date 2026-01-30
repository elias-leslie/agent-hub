"""Claude code execution handler."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import Message, ProviderError
from app.adapters.claude import ClaudeAdapter
from app.api.complete import complete_internal
from app.constants import CLAUDE_SONNET
from app.services.container_manager import ContainerManager
from app.services.memory.citation_parser import extract_uuid_prefixes, resolve_full_uuids

from .debug_logging import log_agent_response, log_tool_call
from .models import AgentConfig, AgentProgress, AgentResult

logger = logging.getLogger(__name__)


async def run_claude_code_execution(
    messages: list[Message],
    config: AgentConfig,
    result: AgentResult,
    adapter: ClaudeAdapter,
    container_manager: ContainerManager,
    progress_callback: Any | None = None,
    db: Any | None = None,
) -> AgentResult:
    """
    Run Claude with code execution enabled.

    Claude handles tool execution internally via its sandbox.
    We just need to continue the conversation if it stops for tool_use.

    Uses complete_internal() on first turn for memory injection and session creation,
    then adapter.complete() for subsequent turns (per decision d3).
    """
    model = config.model or CLAUDE_SONNET

    # Check for existing container to reuse
    container_id = config.container_id
    if container_id:
        container = container_manager.get(container_id)
        if not container:
            container_id = None  # Container expired, don't reuse

    # Track citations across turns (decision d4)
    all_cited_uuids: set[str] = set()
    session_id: str | None = None

    turn = 0
    while turn < config.max_turns:
        turn += 1
        result.turns = turn

        # Report progress
        progress = AgentProgress(
            turn=turn,
            status="running",
            message=f"Turn {turn}: sending to Claude",
        )
        result.progress_log.append(progress)
        if progress_callback:
            await progress_callback(progress)

        try:
            # First turn: use complete_internal for memory injection and session creation
            if turn == 1 and db is not None and isinstance(db, AsyncSession):
                messages_dict = [{"role": m.role, "content": m.content} for m in messages]
                internal_result = await complete_internal(
                    messages=messages_dict,
                    model=model,
                    provider="claude",
                    temperature=config.temperature,
                    project_id=config.project_id,
                    db=db,
                    session_id=session_id,
                    agent_slug=config.agent_slug,
                    use_memory=config.use_memory,
                    memory_group_id=config.memory_group_id,
                    thinking_level=config.thinking_level,
                    enable_programmatic_tools=True,
                    container_id=container_id,
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
                if internal_result.thinking_tokens:
                    result.thinking_tokens += internal_result.thinking_tokens

                # Track container
                if internal_result.container:
                    container_id = internal_result.container.id
                    result.container_id = container_id
                    container_manager.register(
                        container_id=container_id,
                        expires_at=internal_result.container.expires_at,
                        session_id=result.agent_id,
                    )

                finish_reason = internal_result.finish_reason
                content = internal_result.content
                tool_calls = internal_result.tool_calls

                # Debug log response and any tool calls
                log_agent_response(result.agent_id, turn, content, finish_reason or "unknown")
                if tool_calls:
                    for tc in tool_calls:
                        log_tool_call(result.agent_id, turn, tc.name, tc.input)
            else:
                # Subsequent turns: use adapter directly (no memory re-injection)
                completion = await adapter.complete(
                    messages=messages,
                    model=model,
                    temperature=config.temperature,
                    thinking_level=config.thinking_level,
                    tools=None,  # Code execution provides tools
                    enable_programmatic_tools=True,
                    container_id=container_id,
                    working_dir=config.working_dir,
                )

                # Track tokens
                result.input_tokens += completion.input_tokens
                result.output_tokens += completion.output_tokens
                if completion.thinking_tokens:
                    result.thinking_tokens += completion.thinking_tokens

                # Track container
                if completion.container:
                    container_id = completion.container.id
                    result.container_id = container_id
                    container_manager.register(
                        container_id=container_id,
                        expires_at=completion.container.expires_at,
                        session_id=result.agent_id,
                    )

                finish_reason = completion.finish_reason
                content = completion.content
                tool_calls = completion.tool_calls

                # Debug log response and any tool calls
                log_agent_response(result.agent_id, turn, content, finish_reason or "unknown")
                if tool_calls:
                    for tc in tool_calls:
                        log_tool_call(result.agent_id, turn, tc.name, tc.input)

                # Extract citations from subsequent turns
                if content:
                    prefixes = extract_uuid_prefixes(content)
                    if prefixes:
                        group_id = config.memory_group_id or config.project_id
                        prefix_map = await resolve_full_uuids(prefixes, group_id)
                        all_cited_uuids.update(prefix_map.values())
                        logger.debug(
                            "Turn %d: extracted %d citations",
                            turn,
                            len(prefix_map),
                        )

            # Check stop reason
            if finish_reason == "end_turn":
                # Agent completed
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

            elif finish_reason == "tool_use":
                # Claude called tools via code execution
                result.tool_calls_count += len(tool_calls or [])

                # Add assistant's response to conversation
                # The tool results are already in the response from code_execution
                messages.append(Message(role="assistant", content=content))

                progress = AgentProgress(
                    turn=turn,
                    status="tool_use",
                    message=f"Executed {len(tool_calls or [])} tool(s)",
                    tool_calls=[
                        {"name": tc.name, "input": tc.input} for tc in (tool_calls or [])
                    ],
                )
                result.progress_log.append(progress)
                if progress_callback:
                    await progress_callback(progress)

                # Continue conversation - Claude will see tool results
                messages.append(
                    Message(role="user", content="Continue based on the tool results.")
                )

            elif finish_reason == "max_tokens":
                # Hit token limit
                result.status = "error"
                result.error = "Response truncated due to max_tokens"
                result.content = content
                result.cited_uuids = list(all_cited_uuids)
                break

            else:
                # Unknown stop reason
                result.content = content
                if turn == config.max_turns:
                    result.status = "max_turns"
                    result.error = f"Reached maximum turns ({config.max_turns})"
                    result.cited_uuids = list(all_cited_uuids)
                else:
                    # Keep going
                    messages.append(Message(role="assistant", content=content))
                    messages.append(Message(role="user", content="Please continue."))

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
