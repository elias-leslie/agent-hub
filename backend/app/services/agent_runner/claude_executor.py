"""Claude code execution handler."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import CompletionResult, Message, ProviderError
from app.adapters.claude import ClaudeAdapter
from app.api.complete import CompletionInternalResult, complete_internal
from app.constants import CLAUDE_SONNET
from app.services.container_manager import ContainerManager
from app.services.memory.citation_parser import extract_uuid_prefixes, resolve_full_uuids

from .debug_logging import log_agent_response, log_tool_call
from .models import AgentConfig, AgentProgress, AgentResult

logger = logging.getLogger(__name__)


def _track_response(result: AgentResult, container_manager: ContainerManager, response: CompletionInternalResult | CompletionResult) -> str | None:
    """Track tokens and container from API response."""
    result.input_tokens += response.input_tokens
    result.output_tokens += response.output_tokens
    if response.thinking_tokens:
        result.thinking_tokens += response.thinking_tokens
    if response.container:
        cid: str = response.container.id
        result.container_id = cid
        container_manager.register(cid, response.container.expires_at, result.agent_id)
        return cid
    return None


async def _report_progress(result: AgentResult, progress: AgentProgress, callback: Any | None) -> None:
    """Add progress to log and callback."""
    result.progress_log.append(progress)
    if callback:
        await callback(progress)


async def _get_completion(turn: int, db: Any, session_id: str | None, messages: list[Message], config: AgentConfig, model: str, container_id: str | None, adapter: ClaudeAdapter) -> tuple[CompletionInternalResult | CompletionResult, str | None]:
    """Get completion from API."""
    if turn == 1 and db is not None and isinstance(db, AsyncSession):
        internal_resp = await complete_internal(messages=[{"role": m.role, "content": m.content} for m in messages], model=model, provider="claude", temperature=config.temperature, project_id=config.project_id, db=db, session_id=session_id, agent_slug=config.agent_slug, use_memory=config.use_memory, memory_group_id=config.memory_group_id, thinking_level=config.thinking_level, enable_programmatic_tools=True, container_id=container_id, skip_cache=True)
        return internal_resp, internal_resp.session_id
    completion_resp = await adapter.complete(messages=messages, model=model, temperature=config.temperature, thinking_level=config.thinking_level, tools=None, enable_programmatic_tools=True, container_id=container_id, working_dir=config.working_dir)
    return completion_resp, session_id


async def _handle_finish(finish_reason: str | None, turn: int, content: str, tool_calls: list[Any] | None, messages: list[Message], result: AgentResult, config: AgentConfig, uuids: set[str], callback: Any | None) -> bool:
    """Handle finish reason and update result."""
    if finish_reason == "end_turn":
        result.status, result.content, result.cited_uuids = "success", content, list(uuids)
        await _report_progress(result, AgentProgress(turn=turn, status="complete", message="Agent completed task"), callback)
        return True
    if finish_reason == "tool_use":
        result.tool_calls_count += len(tool_calls or [])
        messages.extend([Message(role="assistant", content=content), Message(role="user", content="Continue based on the tool results.")])
        await _report_progress(result, AgentProgress(turn=turn, status="tool_use", message=f"Executed {len(tool_calls or [])} tool(s)", tool_calls=[{"name": tc.name, "input": tc.input} for tc in (tool_calls or [])]), callback)
        return False
    if finish_reason == "max_tokens":
        result.status, result.error, result.content, result.cited_uuids = "error", "Response truncated due to max_tokens", content, list(uuids)
        return True
    if turn == config.max_turns:
        result.status, result.error, result.content, result.cited_uuids = "max_turns", f"Reached maximum turns ({config.max_turns})", content, list(uuids)
    else:
        messages.extend([Message(role="assistant", content=content), Message(role="user", content="Please continue.")])
    return False


async def run_claude_code_execution(messages: list[Message], config: AgentConfig, result: AgentResult, adapter: ClaudeAdapter, container_manager: ContainerManager, progress_callback: Any | None = None, db: Any | None = None) -> AgentResult:
    """Run Claude with code execution enabled."""
    model = config.model or CLAUDE_SONNET
    container_id = config.container_id if config.container_id and container_manager.get(config.container_id) else None
    all_cited_uuids: set[str] = set()
    session_id: str | None = None
    turn = 0

    while turn < config.max_turns:
        turn += 1
        result.turns = turn
        await _report_progress(result, AgentProgress(turn=turn, status="running", message=f"Turn {turn}: sending to Claude"), progress_callback)

        try:
            response, new_session_id = await _get_completion(turn, db, session_id, messages, config, model, container_id, adapter)

            # Update session and citations on first turn
            if turn == 1 and isinstance(response, CompletionInternalResult):
                session_id = result.session_id = new_session_id
                result.memory_uuids = response.memory_uuids
                all_cited_uuids.update(response.cited_uuids)

            container_id = _track_response(result, container_manager, response) or container_id
            finish_reason, content, tool_calls = response.finish_reason, response.content, response.tool_calls

            # Log response and tool calls
            log_agent_response(result.agent_id, turn, content, finish_reason or "unknown")
            for tc in tool_calls or []:
                log_tool_call(result.agent_id, turn, tc.name, tc.input)

            # Extract citations from subsequent turns
            if turn > 1 and content and (prefixes := extract_uuid_prefixes(content)):
                all_cited_uuids.update((await resolve_full_uuids(prefixes, config.memory_group_id or config.project_id)).values())

            if await _handle_finish(finish_reason, turn, content, tool_calls, messages, result, config, all_cited_uuids, progress_callback):
                break

        except ProviderError as e:
            result.status, result.error, result.cited_uuids = "error", str(e), list(all_cited_uuids)
            break

    if result.status == "running":
        result.status, result.error, result.cited_uuids = "max_turns", f"Reached maximum turns ({config.max_turns})", list(all_cited_uuids)

    return result
