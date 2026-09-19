"""Reviewer-agent completion call for memory review batches."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.complete.handler_helpers import save_and_track
from app.api.complete.schemas import CompletionRequest, MessageInput
from app.models import Session as DBSession
from app.services.llm_errors import AuthenticationError, ProviderError, RateLimitError

from ._review_agent_decisions import (
    parse_memory_review_content,
    repair_memory_review_content,
    review_decisions_have_complete_checks,
)
from ._review_agent_prompt import REVIEW_SCHEMA

logger = logging.getLogger(__name__)


async def _call_reviewer_agent(
    db: AsyncSession,
    *,
    reviewer_agent_slug: str,
    prompt: str,
    reviewer_model_id: str | None = None,
    expected_uuids: set[str] | None = None,
    response_schema: dict[str, Any] | None = None,
) -> tuple[str, str | None, str | None]:
    from app.services.agent_routing import get_provider_for_model
    from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent

    resolved = await resolve_agent(reviewer_agent_slug, db)
    mandate = await inject_agent_mandates(
        resolved.agent,
        db,
        prompt_mode="minimal",
        project_id="agent-hub",
        task_type="review",
    )
    messages = _reviewer_messages(mandate.system_content, prompt)
    candidate_models = [
        *([reviewer_model_id] if reviewer_model_id else []),
        resolved.model,
        *list(resolved.agent.fallback_models or []),
    ]
    last_error: Exception | None = None
    repair_candidates: list[tuple[str, str, str | None]] = []
    for model in dict.fromkeys(candidate_models):
        provider = resolved.provider if model == resolved.model else get_provider_for_model(model)
        try:
            result = await _complete_review_with_model(
                db=db,
                messages=messages,
                model=model,
                provider=provider,
                resolved=resolved,
                reviewer_agent_slug=reviewer_agent_slug,
                response_schema=response_schema,
            )
            if getattr(result, "error", None):
                last_error = RuntimeError(f"Memory reviewer model {model} failed: {result.error}")
                logger.warning("%s; trying fallback", last_error)
                continue
            content = result.content.strip()
            parsed = (
                parse_memory_review_content(content, expected_uuids)
                if content and expected_uuids is not None
                else None
            )
            valid = bool(content) and (
                expected_uuids is None or review_decisions_have_complete_checks(parsed)
            )
            if valid:
                return content, model, result.session_id
            if content and expected_uuids is not None:
                repair_candidates.append((content, model, result.session_id))
            last_error = RuntimeError(
                f"Memory reviewer model {model} returned empty or incomplete JSON"
            )
            logger.warning("%s; trying fallback", last_error)
            continue
        except Exception as exc:
            last_error = exc
            if isinstance(exc, AuthenticationError):
                raise
            if not isinstance(exc, RateLimitError) and not (
                isinstance(exc, ProviderError) and exc.retriable
            ):
                raise
            logger.warning("Memory review model %s failed; trying fallback: %s", model, exc)
    if expected_uuids is not None:
        for content, model, session_id in repair_candidates:
            repaired = repair_memory_review_content(content, expected_uuids)
            if repaired is not None:
                logger.warning(
                    "Using quarantined deterministic repair for incomplete memory review from %s",
                    model,
                )
                return repaired, model, session_id
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"No reviewer models configured for {reviewer_agent_slug}")


def _reviewer_messages(system_content: str | None, prompt: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if system_content:
        messages.append({"role": "system", "content": system_content})
    messages.append({"role": "user", "content": prompt})
    return messages


async def _complete_review_with_model(
    *,
    db: AsyncSession,
    messages: list[dict[str, Any]],
    model: str,
    provider: str,
    resolved: Any,
    reviewer_agent_slug: str,
    response_schema: dict[str, Any] | None = None,
) -> Any:
    from app.api.complete.core import complete_internal

    # Reserve a distinct session for every model attempt.  Supplying the id
    # lets us close it even when the provider raises before returning a result.
    session_id = str(uuid4())
    try:
        result = await complete_internal(
            messages=messages,
            model=model,
            provider=provider,
            temperature=resolved.agent.temperature,
            project_id="agent-hub",
            db=db,
            session_id=session_id,
            agent_slug=reviewer_agent_slug,
            request_source="memory_review",
            use_memory=False,
            enable_caching=False,
            skip_cache=True,
            max_turns=1,
            execute_tools=False,
            thinking_level=resolved.agent.thinking_level,
            response_format={"type": "json_object", "schema": response_schema or REVIEW_SCHEMA},
            task_type="review",
            phase="memory_review",
        )
    except Exception as exc:
        await _finalize_review_exception(
            db,
            session_id=session_id,
            model=model,
            provider=provider,
            reviewer_agent_slug=reviewer_agent_slug,
            error=exc,
        )
        raise

    await _persist_review_result(
        db,
        session_id=session_id,
        messages=messages,
        result=result,
        model=model,
        reviewer_agent_slug=reviewer_agent_slug,
        temperature=resolved.agent.temperature,
    )
    return result


async def _persist_review_result(
    db: AsyncSession,
    *,
    session_id: str,
    messages: list[dict[str, Any]],
    result: Any,
    model: str,
    reviewer_agent_slug: str,
    temperature: float,
) -> None:
    """Persist one direct reviewer completion through the canonical accounting path."""
    session = await db.get(DBSession, session_id)
    if session is None:
        raise RuntimeError(f"Memory review completion session {session_id} was not created")
    request = CompletionRequest(
        messages=[MessageInput.model_validate(message) for message in messages],
        model=model,
        temperature=temperature,
        project_id="agent-hub",
        enable_caching=False,
        use_memory=False,
        agent_slug=reviewer_agent_slug,
        max_turns=1,
        execute_tools=False,
        task_type="review",
        phase="memory_review",
    )
    error = getattr(result, "error", None)
    await save_and_track(
        db=db,
        session=session,
        session_id=session_id,
        request=request,
        result=result,
        resolved_model=model,
        model_used=getattr(result, "model_used", None) or getattr(result, "model", None) or model,
        is_new_session=True,
        execution_status="error" if error else "success",
        execution_error=error,
    )


async def _finalize_review_exception(
    db: AsyncSession,
    *,
    session_id: str,
    model: str,
    provider: str,
    reviewer_agent_slug: str,
    error: Exception,
) -> None:
    """Close a reviewer session when the provider raises before a result exists."""
    from app.api.complete.execution_observability import persist_execution_observability
    from app.services.event_storage import store_error_event
    from app.services.session_health import health_detail_for_error
    from app.services.session_live_activity import mark_session_terminal_state

    await db.rollback()
    session = await db.get(DBSession, session_id)
    if session is None:
        logger.warning(
            "Memory review provider failed before session %s was persisted: %s",
            session_id,
            error,
        )
        return
    message = str(error)
    await store_error_event(
        db,
        session_id,
        "MemoryReviewProviderError",
        message,
        agent_id=reviewer_agent_slug,
        model_used=model,
    )
    session.status = "failed"
    session.health_detail = health_detail_for_error(error)
    mark_session_terminal_state(
        session,
        phase="error",
        status="error",
        summary=f"Memory review provider error: {message[:120]}",
        termination_reason=message,
    )
    await persist_execution_observability(
        db,
        session,
        session_id,
        provider=provider,
        model_used=model,
        requested_max_turns=1,
        orchestration_path="single_turn",
        final_finish_reason="error",
        execution_status="error",
        execution_error=message,
        turns_completed=0,
        tool_calls_count=0,
    )
    await db.commit()


__all__ = ["_call_reviewer_agent"]
