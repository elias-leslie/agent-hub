"""Agent runner endpoint - main chat functionality."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.orchestration_models import AgentProgressInfo, AgentRunRequest, AgentRunResponse
from app.db import get_db
from app.models import Message as DBMessage
from app.services.telemetry import get_current_trace_id

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/run-agent", response_model=AgentRunResponse)
async def run_agent(
    request: AgentRunRequest,
    http_request: Request,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> AgentRunResponse:
    """
    Run an agent on a task with tool execution.

    For Claude: Uses code_execution sandbox for autonomous tool calling.
    For Gemini: Uses sandboxed tool executor with bash/read/write tools (supported).

    The agent will execute in a loop, calling tools as needed until the task
    is complete or max_turns is reached.

    When agent_slug is provided, resolves the agent configuration and injects
    mandates into the system prompt.

    Returns:
        AgentRunResponse with execution results and progress log.
    """
    from app.services.agent_runner import AgentConfig, get_agent_runner

    trace_id = get_current_trace_id()
    runner = get_agent_runner()

    resolved_provider = request.provider
    resolved_model = request.model
    system_prompt = request.system_prompt

    if request.agent_slug:
        from app.services.agent_routing import inject_agent_mandates, resolve_agent

        if db is None:
            raise HTTPException(
                status_code=500,
                detail="Database connection required for agent routing.",
            )

        from typing import Literal, cast

        resolved_agent = await resolve_agent(request.agent_slug, db)
        resolved_provider = cast(Literal["claude", "gemini"], resolved_agent.provider)
        resolved_model = request.model or resolved_agent.model

        # Set agent_slug on request.state for access control middleware logging
        http_request.state.agent_slug = request.agent_slug

        mandate_injection = await inject_agent_mandates(resolved_agent.agent, db)
        if mandate_injection.system_content:
            if system_prompt:
                system_prompt = f"{mandate_injection.system_content}\n\n{system_prompt}"
            else:
                system_prompt = mandate_injection.system_content

        logger.info(
            f"Agent routing for run_agent: {request.agent_slug} -> "
            f"{resolved_model} ({resolved_provider}), mandates={len(mandate_injection.injected_uuids)}"
        )

    config = AgentConfig(
        provider=resolved_provider,
        model=resolved_model,
        system_prompt=system_prompt,
        temperature=request.temperature,
        max_turns=request.max_turns,
        thinking_level=request.thinking_level,
        enable_code_execution=request.enable_code_execution,
        container_id=request.container_id,
        working_dir=request.working_dir,
        project_id=request.project_id,
        use_memory=request.use_memory,
        memory_group_id=request.memory_group_id,
        agent_slug=request.agent_slug,
    )

    result = await runner.run(
        task=request.task,
        config=config,
    )

    # Save messages to database for session history
    if db and result.session_id:
        # Save system message if present
        if system_prompt:
            db_msg = DBMessage(
                session_id=result.session_id,
                role="system",
                content=system_prompt,
            )
            db.add(db_msg)

        # Save user task
        db_msg = DBMessage(
            session_id=result.session_id,
            role="user",
            content=request.task,
        )
        db.add(db_msg)

        # Save assistant response
        db_msg = DBMessage(
            session_id=result.session_id,
            role="assistant",
            content=result.content,
            tokens=result.output_tokens,
            model_used=result.model,
        )
        db.add(db_msg)

        await db.commit()

    return AgentRunResponse(
        agent_id=result.agent_id,
        session_id=result.session_id,
        status=result.status,
        content=result.content,
        provider=result.provider,
        model=result.model,
        turns=result.turns,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        thinking_tokens=result.thinking_tokens,
        tool_calls_count=result.tool_calls_count,
        error=result.error,
        progress_log=[
            AgentProgressInfo(
                turn=p.turn,
                status=p.status,
                message=p.message,
                tool_calls=p.tool_calls,
                tool_results=p.tool_results,
                thinking=p.thinking,
            )
            for p in result.progress_log
        ],
        container_id=result.container_id,
        trace_id=trace_id,
        memory_uuids=result.memory_uuids,
        cited_uuids=result.cited_uuids,
    )
