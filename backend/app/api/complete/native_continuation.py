"""Admission, persistence, and response handling for native delta continuations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import NoResultFound

from app.api.complete.event_helpers import save_events
from app.api.complete.helpers import validate_json_response
from app.api.complete.request_setup import inject_memory
from app.api.complete.schemas import (
    CacheInfo,
    CompletionRequest,
    CompletionResponse,
    NativeContinuationInfo,
    UsageInfo,
)
from app.models import NativeContinuationTurn, Session
from app.routing.resolution import inject_agent_system_prompt
from app.services.native_continuation_runtime import (
    NATIVE_TOOL_POLICY_HASH,
    NativeRuntimeError,
    NativeRuntimeKey,
    NativeRuntimeLost,
    NativeTurnObservation,
    get_native_runtime_manager,
)
from app.services.session_live_activity import mark_session_execution_start
from app.services.token_counter import estimate_cost

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.agent_routing import MandateInjection, ResolvedAgent

logger = logging.getLogger(__name__)


def _payload_hash(request: CompletionRequest, resolved_model: str) -> str:
    continuation = request.native_continuation
    assert continuation is not None
    payload = {
        "model": resolved_model,
        "messages": [message.model_dump(mode="json") for message in request.messages],
        "system_prompt": request.system_prompt,
        "response_format": (
            request.response_format.model_dump(mode="json", by_alias=True)
            if request.response_format
            else None
        ),
        "continuation": continuation.model_dump(mode="json"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def _canonical_instructions(
    request: CompletionRequest,
    *,
    session_id: str,
    resolved_agent: ResolvedAgent | None,
    mandate: MandateInjection | None,
    db: AsyncSession,
) -> str:
    messages, _facts, _uuids = await inject_memory(
        request,
        [{"role": "user", "content": str(request.messages[0].content)}],
        session_id,
        resolved_agent,
        db,
    )
    messages = inject_agent_system_prompt(messages, mandate)
    return "\n\n".join(
        str(message["content"])
        for message in messages
        if message.get("role") == "system" and message.get("content")
    )


def _instructions(request: CompletionRequest, canonical: str) -> str:
    parts = [canonical, request.system_prompt or ""]
    if request.response_format and request.response_format.type == "json_object":
        parts.append("Return only a valid JSON object without markdown or surrounding narration.")
    return "\n\n".join(part for part in parts if part)


def _instruction_hash(instructions: str) -> str:
    return hashlib.sha256(instructions.encode()).hexdigest()


def _native_metadata(session: Session) -> dict[str, Any]:
    root = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
    value = root.get("native_continuation")
    return dict(value) if isinstance(value, dict) else {}


def _set_native_metadata(session: Session, value: dict[str, Any]) -> None:
    root = dict(session.provider_metadata) if isinstance(session.provider_metadata, dict) else {}
    root["native_continuation"] = value
    session.provider_metadata = root


def _identity(
    *,
    request: CompletionRequest,
    resolved_model: str,
    client_id: str,
    instruction_hash: str,
    canonical_instruction_hash: str,
) -> dict[str, Any]:
    continuation = request.native_continuation
    assert continuation is not None
    return {
        "generation": continuation.generation,
        "client_id": client_id,
        "project_id": request.project_id,
        "role": continuation.role,
        "controller_generation": continuation.controller_generation,
        "instruction_hash": instruction_hash,
        "canonical_instruction_hash": canonical_instruction_hash,
        "tool_policy_hash": NATIVE_TOOL_POLICY_HASH,
        "model": resolved_model,
        "reasoning_effort": continuation.reasoning_effort,
        "cyber_access_program": continuation.cyber_access_program,
    }


def _response_from_receipt(
    receipt: NativeContinuationTurn,
    session_id: str,
    *,
    duplicate: bool,
) -> CompletionResponse:
    cache = (
        CacheInfo(
            cache_creation_input_tokens=0,
            cache_read_input_tokens=receipt.cache_read_tokens,
            cache_hit_rate=(
                min(1.0, receipt.cache_read_tokens / receipt.input_tokens)
                if receipt.input_tokens
                else 0.0
            ),
        )
        if receipt.cache_read_tokens
        else None
    )
    return CompletionResponse(
        content=receipt.content or "",
        model=receipt.model_used or "unavailable",
        provider="codex-native",
        usage=UsageInfo(
            input_tokens=receipt.input_tokens,
            output_tokens=receipt.output_tokens,
            total_tokens=receipt.input_tokens + receipt.output_tokens,
            cache=cache,
        ),
        session_id=session_id,
        finish_reason="stop",
        agent_used=receipt.agent_used,
        model_used=receipt.model_used or "unavailable",
        native_continuation=NativeContinuationInfo(
            generation=receipt.generation,
            turn=receipt.accepted_turn,
            request_id=receipt.request_id,
            context_version=receipt.context_version,
            instruction_hash=receipt.instruction_hash,
            tool_policy_hash=receipt.tool_policy_hash,
            native_thread_id=receipt.native_thread_id or "unavailable",
            native_turn_id=receipt.native_turn_id,
            runtime_status=receipt.runtime_status,
            duplicate=duplicate,
            input_mode="snapshot" if receipt.expected_turn == 0 else "delta",
            reasoning_tokens=receipt.reasoning_tokens,
            usage_known=receipt.usage_known,
        ),
    )


async def _find_receipt(
    db: AsyncSession, session_id: str, generation: int, request_id: str
) -> NativeContinuationTurn | None:
    result = await db.execute(
        select(NativeContinuationTurn).where(
            NativeContinuationTurn.session_id == session_id,
            NativeContinuationTurn.generation == generation,
            NativeContinuationTurn.request_id == request_id,
        )
    )
    return result.scalar_one_or_none()


def _validate_session_owner(
    session: Session, *, client_id: str, project_id: str
) -> None:
    if session.project_id != project_id or session.client_id != client_id:
        raise HTTPException(status_code=404, detail="Native continuation session not found.")


def _validate_delta(
    request: CompletionRequest, metadata: dict[str, Any], identity: dict[str, Any]
) -> None:
    continuation = request.native_continuation
    assert continuation is not None
    if not metadata:
        raise HTTPException(
            status_code=409,
            detail="No retained native generation exists. Start with a snapshot.",
        )
    for field in (
        "generation",
        "client_id",
        "project_id",
        "role",
        "controller_generation",
        "instruction_hash",
        "canonical_instruction_hash",
        "tool_policy_hash",
        "model",
        "reasoning_effort",
        "cyber_access_program",
    ):
        if metadata.get(field) != identity[field]:
            raise HTTPException(
                status_code=409,
                detail=f"Native continuation {field} changed; start a higher generation snapshot.",
            )
    if metadata.get("status") != "active":
        raise HTTPException(
            status_code=409,
            detail="The native generation is not active. Start a higher generation snapshot.",
        )
    if continuation.expected_turn != metadata.get("turn"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Native continuation expected_turn={continuation.expected_turn} does not match "
                f"the recorded turn={metadata.get('turn')}."
            ),
        )
    if continuation.context_version == metadata.get("context_version"):
        raise HTTPException(
            status_code=409,
            detail="Delta context_version must advance from the previous accepted input.",
        )


def _validate_snapshot(metadata: dict[str, Any], generation: int) -> None:
    if metadata.get("status") in {"starting", "turn_pending"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "The current native turn is still pending. Let it settle or close its exact "
                "generation before starting a replacement snapshot."
            ),
        )
    previous = metadata.get("generation")
    if isinstance(previous, int) and generation <= previous:
        raise HTTPException(
            status_code=409,
            detail=f"Snapshot generation must be higher than the recorded generation={previous}.",
        )


def _owns_pending_turn(
    metadata: dict[str, Any], identity: dict[str, Any], request_id: str
) -> bool:
    fields = (
        "generation",
        "client_id",
        "project_id",
        "role",
        "controller_generation",
        "instruction_hash",
        "canonical_instruction_hash",
        "tool_policy_hash",
        "model",
        "reasoning_effort",
        "cyber_access_program",
    )
    return (
        all(metadata.get(field) == identity[field] for field in fields)
        and metadata.get("request_id") == request_id
        and metadata.get("status") in {"starting", "turn_pending"}
    )


async def _lock_session(db: AsyncSession, session_id: str) -> Session:
    from app.models import Session as DBSession

    locked = await db.execute(
        select(DBSession)
        .where(DBSession.id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return locked.scalar_one()


async def _lock_or_create_native_session(
    db: AsyncSession,
    request: CompletionRequest,
    *,
    provider: str,
    resolved_model: str,
    client_id: str,
    request_source: str | None,
) -> tuple[Session, bool]:
    """Serialize admission without loading transcripts or rewriting stale JSON metadata."""
    from app.constants.projects import validate_project_id

    assert request.session_id is not None
    await validate_project_id(request.project_id)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"native-continuation:{request.session_id}"},
    )
    row = await db.execute(
        select(Session).where(Session.id == request.session_id).with_for_update()
    )
    session = row.scalar_one_or_none()
    if session is not None:
        _validate_session_owner(session, client_id=client_id, project_id=request.project_id)
        return session, False

    now = datetime.now(UTC)
    session = Session(
        id=request.session_id,
        project_id=request.project_id,
        provider=provider,
        model=resolved_model,
        status="active",
        session_type="completion",
        agent_slug=request.agent_slug,
        external_id=request.external_id,
        client_id=client_id,
        request_source=request_source,
        current_branch=request.current_branch,
        provider_metadata={
            "requested_model": resolved_model,
            "requested_provider": provider,
            "effective_model": resolved_model,
            "effective_provider": provider,
            "fallback_used": False,
            **({"trace_id": request.trace_id} if request.trace_id else {}),
        },
        models_used=[resolved_model],
        providers_used=[provider],
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    await db.flush()
    return session, True


def _validate_output(request: CompletionRequest, content: str) -> None:
    response_format = request.response_format
    if not response_format or response_format.type != "json_object":
        return
    try:
        json.loads(content)
    except (TypeError, json.JSONDecodeError) as exc:
        raise NativeRuntimeError(
            "native_output_invalid", "Native reasoning did not return a JSON object."
        ) from exc
    if response_format.schema_:
        valid, error = validate_json_response(content, response_format.schema_)
        if not valid:
            raise NativeRuntimeError(
                "native_output_invalid", f"Native output failed its JSON schema: {error}"
            )


async def _persist_db_usage(
    db: AsyncSession,
    session: Session,
    request: CompletionRequest,
    result: NativeTurnObservation,
    resolved_model: str,
) -> None:
    from app.services.context_tracker import log_token_usage

    usage = result.usage
    billing_model = result.observed_model or resolved_model
    source_metadata = (
        request.source_metadata.model_dump(exclude_none=True)
        if request.source_metadata is not None
        else None
    )
    await save_events(
        db,
        session.id,
        request.messages,
        result.answer_text,
        usage.input_tokens,
        usage.output_tokens,
        billing_model,
        agent_id=request.agent_slug,
        source_metadata=source_metadata,
        commit=False,
    )
    cost = estimate_cost(
        usage.input_tokens,
        usage.output_tokens,
        billing_model,
        cached_input_tokens=usage.cache_read_tokens,
    )
    await log_token_usage(
        db,
        session.id,
        billing_model,
        usage.input_tokens,
        usage.output_tokens,
        cost.total_cost_usd,
        cache_read_tokens=usage.cache_read_tokens,
    )


async def _persist_external_usage(
    request: CompletionRequest,
    session_id: str,
    result: NativeTurnObservation,
    resolved_model: str,
) -> None:
    from app.services.events import publish_complete
    from app.services.project_budget import record_project_cost
    from app.services.quota import record_token_usage

    usage = result.usage
    billing_model = result.observed_model or resolved_model
    cost = estimate_cost(
        usage.input_tokens,
        usage.output_tokens,
        billing_model,
        cached_input_tokens=usage.cache_read_tokens,
    )
    try:
        await publish_complete(
            session_id, usage.input_tokens, usage.output_tokens, cost.total_cost_usd
        )
        if request.agent_slug:
            await record_token_usage(
                request.agent_slug, usage.input_tokens + usage.output_tokens
            )
        if cost.total_cost_usd > 0:
            await record_project_cost(request.project_id, cost.total_cost_usd)
    except Exception:
        logger.exception(
            "Native continuation completed but external quota/budget telemetry failed: %s",
            session_id,
        )


async def execute_native_continuation(
    request: CompletionRequest,
    *,
    resolved_model: str,
    provider: str,
    resolved_agent: ResolvedAgent | None,
    mandate: MandateInjection | None,
    agent_used: str | None,
    db: AsyncSession | None,
    client_id: str | None,
    request_source: str | None,
) -> CompletionResponse:
    """Execute one admitted snapshot/delta without rebuilding stored transcript context."""
    continuation = request.native_continuation
    assert continuation is not None
    if db is None or not client_id:
        raise HTTPException(
            status_code=401,
            detail="Native continuation requires an authenticated persisted client session.",
        )
    if provider != "codex" and not resolved_model.startswith("codex/"):
        raise HTTPException(
            status_code=400, detail="Native continuation is available only for Codex models."
        )
    expected_agent = f"neri-{continuation.role}"
    if request.project_id != "neri" or agent_used != expected_agent:
        raise HTTPException(
            status_code=400,
            detail=(
                "Native continuation is currently limited to the registered Neri hunter and "
                "reviewer roles."
            ),
        )
    if request.model is not None or not request.disable_agent_fallbacks:
        raise HTTPException(
            status_code=400,
            detail=(
                "Native Neri continuation requires canonical agent routing with fallbacks disabled."
            ),
        )

    session, is_new_session = await _lock_or_create_native_session(
        db,
        request,
        provider=provider,
        resolved_model=resolved_model,
        client_id=client_id,
        request_source=request_source,
    )
    session_id = session.id
    payload_hash = _payload_hash(request, resolved_model)
    existing = await _find_receipt(
        db, session_id, continuation.generation, continuation.request_id
    )
    metadata = _native_metadata(session)
    if existing is not None:
        if existing.payload_hash != payload_hash:
            raise HTTPException(
                status_code=409,
                detail="Native request_id was already accepted with a different payload.",
            )
        if existing.status == "completed":
            return _response_from_receipt(existing, session_id, duplicate=True)
        raise HTTPException(
            status_code=409,
            detail=(
                "The native request was already accepted without a reusable completed result. "
                "It was not replayed; start a higher generation snapshot."
            ),
        )

    canonical_instructions = await _canonical_instructions(
        request,
        session_id=session_id,
        resolved_agent=resolved_agent,
        mandate=mandate,
        db=db,
    )
    instructions = (
        _instructions(request, canonical_instructions)
        if continuation.mode == "snapshot"
        else ""
    )
    actual_instruction_hash = (
        _instruction_hash(instructions)
        if continuation.mode == "snapshot"
        else str(continuation.instruction_hash)
    )
    if continuation.mode == "snapshot" and continuation.instruction_hash not in (
        None,
        actual_instruction_hash,
    ):
        raise HTTPException(
            status_code=409,
            detail="Snapshot instruction_hash does not match the resolved instructions.",
        )
    if continuation.tool_policy_hash not in (None, NATIVE_TOOL_POLICY_HASH):
        raise HTTPException(
            status_code=409,
            detail="Native tool policy changed; start a new snapshot using the current policy hash.",
        )
    identity = _identity(
        request=request,
        resolved_model=resolved_model,
        client_id=client_id,
        instruction_hash=actual_instruction_hash,
        canonical_instruction_hash=_instruction_hash(canonical_instructions),
    )
    if continuation.mode == "snapshot":
        _validate_snapshot(metadata, continuation.generation)
    else:
        _validate_delta(request, metadata, identity)

    accepted_turn = continuation.expected_turn + 1
    receipt = NativeContinuationTurn(
        session_id=session_id,
        generation=continuation.generation,
        request_id=continuation.request_id,
        payload_hash=payload_hash,
        expected_turn=continuation.expected_turn,
        accepted_turn=accepted_turn,
        context_version=continuation.context_version,
        instruction_hash=actual_instruction_hash,
        tool_policy_hash=NATIVE_TOOL_POLICY_HASH,
        runtime_status=("starting" if continuation.mode == "snapshot" else "turn_pending"),
        agent_used=expected_agent,
        status="accepted",
    )
    db.add(receipt)
    mark_session_execution_start(session)
    pending_metadata = {
        **identity,
        "turn": continuation.expected_turn,
        "context_version": metadata.get("context_version"),
        "status": "starting" if continuation.mode == "snapshot" else "turn_pending",
        "request_id": continuation.request_id,
    }
    _set_native_metadata(session, pending_metadata)
    await db.commit()
    if is_new_session:
        from app.services.events import publish_session_start

        try:
            await publish_session_start(session_id, resolved_model, request.project_id)
        except Exception:
            logger.exception("Native session persisted but start telemetry failed: %s", session_id)

    runtime_key = NativeRuntimeKey(
        session_id=session_id,
        generation=continuation.generation,
        client_id=client_id,
        project_id=request.project_id,
        role=continuation.role,
        controller_generation=continuation.controller_generation,
        instruction_hash=actual_instruction_hash,
        tool_policy_hash=NATIVE_TOOL_POLICY_HASH,
        model=resolved_model,
        reasoning_effort=continuation.reasoning_effort,
        cyber_access_program=continuation.cyber_access_program,
    )
    output_schema = request.response_format.schema_ if request.response_format else None
    result: NativeTurnObservation | None = None
    try:
        result = await get_native_runtime_manager().execute(
            runtime_key,
            mode=continuation.mode,
            instructions=instructions,
            prompt=str(request.messages[0].content),
            output_schema=output_schema,
            close_after=continuation.close_after,
        )
        _validate_output(request, result.answer_text)
    except NativeRuntimeError as exc:
        result = result or exc.observation
        await get_native_runtime_manager().close(session_id, continuation.generation)
        session = await _lock_session(db, session_id)
        receipt.status = "failed"
        receipt.runtime_status = "unavailable"
        receipt.error_code = exc.code
        if result is not None:
            receipt.native_thread_id = result.thread_id
            receipt.native_turn_id = result.turn_id
            receipt.model_used = result.observed_model
            receipt.input_tokens = result.usage.input_tokens
            receipt.cache_read_tokens = result.usage.cache_read_tokens
            receipt.output_tokens = result.usage.output_tokens
            receipt.reasoning_tokens = result.usage.reasoning_tokens
            receipt.usage_known = result.usage.known
            await _persist_db_usage(db, session, request, result, resolved_model)
        failed = {
            **pending_metadata,
            "status": "unavailable",
            "last_error_code": exc.code,
        }
        if _owns_pending_turn(
            _native_metadata(session), identity, continuation.request_id
        ):
            _set_native_metadata(session, failed)
        await db.commit()
        if result is not None:
            await _persist_external_usage(request, session_id, result, resolved_model)
        status = 409 if isinstance(exc, NativeRuntimeLost) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except asyncio.CancelledError:
        await get_native_runtime_manager().close(session_id, continuation.generation)
        session = await _lock_session(db, session_id)
        receipt.status = "failed"
        receipt.runtime_status = "unavailable"
        receipt.error_code = "native_cancelled"
        if _owns_pending_turn(
            _native_metadata(session), identity, continuation.request_id
        ):
            _set_native_metadata(
                session,
                {
                    **pending_metadata,
                    "status": "unavailable",
                    "last_error_code": "native_cancelled",
                },
            )
        await db.commit()
        raise
    except TimeoutError as exc:
        session = await _lock_session(db, session_id)
        receipt.status = "failed"
        receipt.runtime_status = "unavailable"
        receipt.error_code = "native_timeout"
        if _owns_pending_turn(
            _native_metadata(session), identity, continuation.request_id
        ):
            _set_native_metadata(
                session,
                {
                    **pending_metadata,
                    "status": "unavailable",
                    "last_error_code": "native_timeout",
                },
            )
        await db.commit()
        raise HTTPException(
            status_code=504,
            detail="Native reasoning exceeded the existing 180-second turn budget.",
        ) from exc

    session = await _lock_session(db, session_id)
    owns_terminal_state = _owns_pending_turn(
        _native_metadata(session), identity, continuation.request_id
    )
    receipt.status = "completed" if owns_terminal_state else "superseded"
    receipt.native_thread_id = result.thread_id
    receipt.native_turn_id = result.turn_id
    receipt.content = result.answer_text
    receipt.model_used = result.observed_model
    receipt.input_tokens = result.usage.input_tokens
    receipt.cache_read_tokens = result.usage.cache_read_tokens
    receipt.output_tokens = result.usage.output_tokens
    receipt.reasoning_tokens = result.usage.reasoning_tokens
    receipt.usage_known = result.usage.known
    receipt.runtime_status = (
        ("closed" if continuation.close_after else "active")
        if owns_terminal_state
        else "superseded"
    )
    completed_metadata = {
        **identity,
        "turn": accepted_turn,
        "context_version": continuation.context_version,
        "status": "closed" if continuation.close_after else "active",
        "request_id": continuation.request_id,
        "native_thread_id": result.thread_id,
        "native_turn_id": result.turn_id,
        "runtime": result.runtime,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if owns_terminal_state:
        _set_native_metadata(session, completed_metadata)
    await _persist_db_usage(db, session, request, result, resolved_model)
    await db.commit()
    await _persist_external_usage(request, session_id, result, resolved_model)
    if not owns_terminal_state:
        raise HTTPException(
            status_code=409,
            detail=(
                "Native turn completed after its generation lost ownership. The result was recorded "
                "for audit but was not returned as a current proposal."
            ),
        )
    return _response_from_receipt(receipt, session_id, duplicate=False)


async def close_native_continuation(
    *,
    session_id: str,
    generation: int,
    controller_generation: str,
    client_id: str | None,
    db: AsyncSession | None,
) -> dict[str, Any]:
    """Close one exact live generation without executing or replaying a turn."""
    if db is None or not client_id:
        raise HTTPException(status_code=401, detail="Authenticated client required.")
    try:
        session = await _lock_session(db, session_id)
    except NoResultFound as exc:
        raise HTTPException(
            status_code=404, detail="Native continuation session not found."
        ) from exc
    if session.client_id != client_id:
        raise HTTPException(status_code=404, detail="Native continuation session not found.")
    metadata = _native_metadata(session)
    if (
        metadata.get("generation") != generation
        or metadata.get("controller_generation") != controller_generation
    ):
        raise HTTPException(status_code=409, detail="Native continuation generation changed.")
    _set_native_metadata(session, {**metadata, "status": "closing"})
    await db.commit()
    closed = await get_native_runtime_manager().close(session_id, generation)
    session = await _lock_session(db, session_id)
    metadata = _native_metadata(session)
    if (
        metadata.get("generation") != generation
        or metadata.get("controller_generation") != controller_generation
        or metadata.get("status") != "closing"
    ):
        raise HTTPException(status_code=409, detail="Native continuation generation changed.")
    _set_native_metadata(session, {**metadata, "status": "closed"})
    await db.commit()
    return {"session_id": session_id, "generation": generation, "closed": closed, "status": "closed"}
