"""Bounded TypeSafe Jev dispatch with typed outputs and a durable total-cost ledger."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.typesafe_jev_schemas import (
    ChoiceAnswer,
    ChoiceQuestion,
    JevBudgetView,
    JevUsage,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
    TypeSafeJevRequest,
    TypeSafeJevResult,
    TypeSafeProviderResponse,
)
from app.models.typesafe_jev import TypeSafeJevBudget, TypeSafeJevDispatch
from app.services.credential_manager import get_credential_manager

TYPESAFE_PROVIDER_ID = "typesafe"
TYPESAFE_API_URL = "https://api.typesafe.ai/v1/systemone"
TYPESAFE_KEY_FILE = Path("/home/kasadis/.config/typesafe/credentials.env")
TYPESAFE_KEY_NAME = "TYPESAFE_API_KEY"

PILOT_BUDGET_KEY = "-".join(("neri", "jev", "pilot", "2026", "09"))
PILOT_CEILING_USD = Decimal("5.000000000")
JEV_MODEL_ID = "jev-1.13.0"
JEV_INPUT_USD_PER_MILLION = Decimal("0.042")
JEV_MAX_INPUT_TOKENS = 64_000
JEV_RESERVED_COST_USD = Decimal(JEV_MAX_INPUT_TOKENS) * JEV_INPUT_USD_PER_MILLION / Decimal(
    1_000_000
)
JEV_PRICING_CONTRACT = "jev-1.13.0:usd-0.042-per-million-input:2026-09-19"
JEV_PRICING_SOURCE = "https://docs.typesafe.ai/models"
_MONEY_QUANTUM = Decimal("0.000000001")


class TypeSafeJevError(RuntimeError):
    """A fail-visible client, contract, budget, or provider error."""

    def __init__(
        self,
        kind: str,
        detail: str,
        *,
        status_code: int = 409,
        provider_request_id: str | None = None,
        provider_response: TypeSafeProviderResponse | None = None,
    ) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
        self.status_code = status_code
        self.provider_request_id = provider_request_id
        self.provider_response = provider_response


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_QUANTUM)


def _cost_for_input_tokens(tokens: int) -> Decimal:
    return _money(Decimal(tokens) * JEV_INPUT_USD_PER_MILLION / Decimal(1_000_000))


def _request_payload(request: TypeSafeJevRequest) -> dict[str, Any]:
    return {
        "state": request.state,
        "model": request.model,
        "questions": {
            key: question.model_dump(mode="json", exclude_none=True)
            for key, question in request.questions.items()
        },
    }


def _request_sha256(request: TypeSafeJevRequest) -> str:
    identity = {
        "payload": _request_payload(request),
        "pricing_contract": request.pricing_contract,
        "sources": [source.model_dump(mode="json") for source in request.sources],
        "rubric": request.rubric.model_dump(mode="json"),
        "observation": request.observation.model_dump(mode="json") if request.observation else None,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_key_file(path: Path = TYPESAFE_KEY_FILE) -> str:
    """Read one exact owner-only assignment without executing shell syntax."""
    try:
        metadata = path.stat()
    except OSError as exc:
        raise TypeSafeJevError("credential_unavailable", "TypeSafe credential file is unavailable") from exc
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise TypeSafeJevError(
            "credential_permissions",
            "TypeSafe credential file must be owned by the service user and mode 0600",
        )

    values: list[str] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                name, separator, value = line.partition("=")
                if separator and name.strip() == TYPESAFE_KEY_NAME:
                    values.append(value.strip())
    except OSError as exc:
        raise TypeSafeJevError("credential_unavailable", "TypeSafe credential file is unreadable") from exc

    if len(values) != 1 or not values[0]:
        raise TypeSafeJevError(
            "credential_invalid",
            f"credential file must contain exactly one non-empty {TYPESAFE_KEY_NAME} assignment",
        )
    return values[0]


def resolve_typesafe_api_key() -> str:
    """Prefer Agent Hub's encrypted broker, then the approved pilot-only file."""
    manager = get_credential_manager()
    if manager.is_initialized:
        key = manager.get_api_key(TYPESAFE_PROVIDER_ID)
        if key:
            return key
    return _load_key_file()


def _validate_provider_response(
    request: TypeSafeJevRequest,
    response: TypeSafeProviderResponse,
) -> None:
    if response.model != JEV_MODEL_ID:
        raise TypeSafeJevError(
            "model_version_changed",
            f"expected {JEV_MODEL_ID}, provider reported {response.model}",
            status_code=502,
        )
    if response.usage.input_tokens > JEV_MAX_INPUT_TOKENS:
        raise TypeSafeJevError(
            "provider_contract_changed",
            "provider reported input usage above the documented 64k request limit",
            status_code=502,
        )
    if response.answers.keys() != request.questions.keys():
        raise TypeSafeJevError(
            "unsupported_output",
            "provider answer ids did not exactly match the requested question ids",
            status_code=502,
        )

    for question_id, question in request.questions.items():
        answer = response.answers[question_id]
        if isinstance(question, NoulQuestion):
            if not isinstance(answer, NoulAnswer):
                raise TypeSafeJevError("unsupported_output", f"{question_id} answer type changed", status_code=502)
            continue
        if isinstance(question, ChoiceQuestion):
            if not isinstance(answer, ChoiceAnswer):
                raise TypeSafeJevError("unsupported_output", f"{question_id} answer type changed", status_code=502)
            expected = set(question.criteria)
            if answer.choice not in expected or set(answer.probabilities) != expected:
                raise TypeSafeJevError(
                    "unsupported_output",
                    f"{question_id} choice output did not preserve the requested rubric",
                    status_code=502,
                )
            if any(probability < 0 or probability > 1 for probability in answer.probabilities.values()):
                raise TypeSafeJevError("unsupported_output", f"{question_id} probabilities were invalid", status_code=502)
            continue
        if not isinstance(question, ScoreQuestion) or not isinstance(answer, ScoreAnswer):
            raise TypeSafeJevError("unsupported_output", f"{question_id} answer type changed", status_code=502)
        expected_levels = {str(index) for index in range(len(question.criteria))}
        if set(answer.legend) != expected_levels or set(answer.probabilities) != expected_levels:
            raise TypeSafeJevError(
                "unsupported_output",
                f"{question_id} score output did not preserve the requested rubric",
                status_code=502,
            )
        if not 0 <= answer.score <= len(question.criteria) - 1:
            raise TypeSafeJevError("unsupported_output", f"{question_id} score was out of range", status_code=502)
        if any(probability < 0 or probability > 1 for probability in answer.probabilities.values()):
            raise TypeSafeJevError("unsupported_output", f"{question_id} probabilities were invalid", status_code=502)


def _budget_view(
    budget: TypeSafeJevBudget,
    *,
    reservation_usd: Decimal = JEV_RESERVED_COST_USD,
) -> JevBudgetView:
    available = _money(budget.ceiling_usd - budget.spent_usd - budget.reserved_usd)
    return JevBudgetView(
        ceiling_usd=f"{_money(budget.ceiling_usd):.9f}",
        spent_usd=f"{_money(budget.spent_usd):.9f}",
        reserved_usd=f"{_money(budget.reserved_usd):.9f}",
        available_usd=f"{available:.9f}",
        reservation_usd=f"{_money(reservation_usd):.9f}",
    )


def _assert_budget_contract(budget: TypeSafeJevBudget) -> None:
    if (
        budget.ceiling_usd != PILOT_CEILING_USD
        or budget.model_id != JEV_MODEL_ID
        or budget.pricing_contract != JEV_PRICING_CONTRACT
    ):
        raise TypeSafeJevError(
            "budget_contract_changed",
            "stored Jev budget, model, or pricing contract differs from the approved pilot",
        )


async def _locked_budget(db: AsyncSession) -> TypeSafeJevBudget:
    budget = await db.scalar(
        select(TypeSafeJevBudget)
        .where(TypeSafeJevBudget.key == PILOT_BUDGET_KEY)
        .with_for_update()
    )
    if budget is None:
        raise TypeSafeJevError("budget_missing", "TypeSafe Jev pilot budget is not initialized", status_code=503)
    _assert_budget_contract(budget)
    return budget


async def _existing_dispatch(
    db: AsyncSession,
    *,
    request_id: str,
    request_sha256: str,
) -> tuple[TypeSafeJevDispatch | None, bool]:
    by_id = await db.get(TypeSafeJevDispatch, request_id)
    if by_id is not None:
        if by_id.request_sha256 != request_sha256:
            raise TypeSafeJevError("request_id_conflict", "request_id was reused with different content")
        return by_id, True
    by_digest = await db.scalar(
        select(TypeSafeJevDispatch).where(TypeSafeJevDispatch.request_sha256 == request_sha256)
    )
    return by_digest, by_digest is not None


def _result_from_dispatch(
    dispatch: TypeSafeJevDispatch,
    budget: TypeSafeJevBudget,
    *,
    deduplicated: bool,
) -> TypeSafeJevResult:
    answers = None
    if dispatch.answers is not None:
        answers = TypeSafeProviderResponse.model_validate(
            {
                "model": dispatch.model_observed,
                "answers": dispatch.answers,
                "usage": {
                    "input_tokens": dispatch.actual_input_tokens,
                    "output_tokens": dispatch.actual_output_tokens,
                },
            }
        ).answers
    usage = None
    if dispatch.actual_input_tokens is not None and dispatch.actual_output_tokens is not None:
        usage = JevUsage(
            input_tokens=dispatch.actual_input_tokens,
            output_tokens=dispatch.actual_output_tokens,
        )
    from app.api.typesafe_jev_schemas import (
        ObservationProvenance,
        RubricProvenance,
        SourceProvenance,
    )

    return TypeSafeJevResult(
        request_id=dispatch.request_id,
        request_sha256=dispatch.request_sha256,
        status=dispatch.status,
        deduplicated=deduplicated,
        model_requested=dispatch.model_requested,
        model_observed=dispatch.model_observed,
        pricing_contract=dispatch.pricing_contract,
        provider_request_id=dispatch.provider_request_id,
        usage=usage,
        answers=answers,
        budget=_budget_view(budget),
        sources=[SourceProvenance.model_validate(value) for value in dispatch.source_provenance],
        rubric=RubricProvenance.model_validate(dispatch.rubric_provenance),
        observation=(
            ObservationProvenance.model_validate(dispatch.observation_provenance)
            if dispatch.observation_provenance
            else None
        ),
        error_kind=dispatch.error_kind,
        error_detail=dispatch.error_detail,
    )


async def _reserve(
    db: AsyncSession,
    request: TypeSafeJevRequest,
    request_sha256: str,
) -> tuple[TypeSafeJevDispatch, TypeSafeJevBudget, bool]:
    budget = await _locked_budget(db)
    existing, deduplicated = await _existing_dispatch(
        db,
        request_id=str(request.request_id),
        request_sha256=request_sha256,
    )
    if existing is not None:
        return existing, budget, deduplicated

    available = budget.ceiling_usd - budget.spent_usd - budget.reserved_usd
    if available < JEV_RESERVED_COST_USD:
        raise TypeSafeJevError(
            "budget_exhausted",
            "the remaining Jev pilot budget cannot cover one documented maximum-size request",
            status_code=402,
        )
    dispatch = TypeSafeJevDispatch(
        request_id=str(request.request_id),
        budget_key=PILOT_BUDGET_KEY,
        request_sha256=request_sha256,
        status="reserved",
        model_requested=request.model,
        pricing_contract=request.pricing_contract,
        reserved_input_tokens=JEV_MAX_INPUT_TOKENS,
        reserved_cost_usd=JEV_RESERVED_COST_USD,
        source_provenance=[source.model_dump(mode="json") for source in request.sources],
        rubric_provenance=request.rubric.model_dump(mode="json"),
        observation_provenance=(
            request.observation.model_dump(mode="json") if request.observation else None
        ),
    )
    budget.reserved_usd = _money(budget.reserved_usd + JEV_RESERVED_COST_USD)
    db.add(dispatch)
    await db.commit()
    return dispatch, budget, False


async def _mark_uncertain(
    db: AsyncSession,
    dispatch: TypeSafeJevDispatch,
    *,
    kind: str,
    detail: str,
    provider_request_id: str | None = None,
) -> TypeSafeJevBudget:
    budget = await _locked_budget(db)
    current = await db.get(TypeSafeJevDispatch, dispatch.request_id)
    if current is None:
        raise TypeSafeJevError("ledger_inconsistent", "reserved dispatch disappeared", status_code=503)
    current.status = "uncertain"
    current.error_kind = kind
    current.error_detail = detail
    current.provider_request_id = provider_request_id
    current.completed_at = datetime.now(UTC)
    await db.commit()
    return budget


async def _finalize_known(
    db: AsyncSession,
    dispatch: TypeSafeJevDispatch,
    response: TypeSafeProviderResponse,
    *,
    provider_request_id: str | None,
    validation_error: TypeSafeJevError | None,
) -> tuple[TypeSafeJevDispatch, TypeSafeJevBudget]:
    budget = await _locked_budget(db)
    current = await db.get(TypeSafeJevDispatch, dispatch.request_id)
    if current is None:
        raise TypeSafeJevError("ledger_inconsistent", "reserved dispatch disappeared", status_code=503)
    actual_cost = _cost_for_input_tokens(response.usage.input_tokens)
    budget.reserved_usd = _money(budget.reserved_usd - current.reserved_cost_usd)
    budget.spent_usd = _money(budget.spent_usd + actual_cost)
    current.status = "failed" if validation_error else "succeeded"
    current.model_observed = response.model
    current.actual_input_tokens = response.usage.input_tokens
    current.actual_output_tokens = response.usage.output_tokens
    current.actual_cost_usd = actual_cost
    current.provider_request_id = provider_request_id
    current.answers = (
        None
        if validation_error
        else {key: answer.model_dump(mode="json") for key, answer in response.answers.items()}
    )
    current.error_kind = validation_error.kind if validation_error else None
    current.error_detail = validation_error.detail if validation_error else None
    current.completed_at = datetime.now(UTC)
    await db.commit()
    return current, budget


async def _finalize_not_dispatched(
    db: AsyncSession,
    dispatch: TypeSafeJevDispatch,
    error: TypeSafeJevError,
) -> tuple[TypeSafeJevDispatch, TypeSafeJevBudget]:
    """Release a reservation when a local failure proves no provider call occurred."""
    budget = await _locked_budget(db)
    current = await db.get(TypeSafeJevDispatch, dispatch.request_id)
    if current is None:
        raise TypeSafeJevError("ledger_inconsistent", "reserved dispatch disappeared", status_code=503)
    budget.reserved_usd = _money(budget.reserved_usd - current.reserved_cost_usd)
    current.status = "failed"
    current.error_kind = error.kind
    current.error_detail = error.detail
    current.completed_at = datetime.now(UTC)
    await db.commit()
    return current, budget


async def call_typesafe_jev(
    request: TypeSafeJevRequest,
    *,
    api_key: str,
    http_client: httpx.AsyncClient | None = None,
) -> tuple[TypeSafeProviderResponse, str | None]:
    """Call the official HTTP endpoint once and return a fully validated response."""
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=None, trust_env=False, follow_redirects=False)
    try:
        response = await client.post(
            TYPESAFE_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=_request_payload(request),
        )
        provider_request_id = response.headers.get("x-typesafe-request-id")
        if not response.is_success:
            raise TypeSafeJevError(
                "provider_http_error",
                f"TypeSafe returned HTTP {response.status_code}; billing is uncertain",
                status_code=502,
                provider_request_id=provider_request_id,
            )
        try:
            provider_response = TypeSafeProviderResponse.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise TypeSafeJevError(
                "unsupported_output",
                "TypeSafe returned an unsupported response; billing is uncertain",
                status_code=502,
            ) from exc
        try:
            _validate_provider_response(request, provider_response)
        except TypeSafeJevError as exc:
            exc.provider_request_id = provider_request_id
            exc.provider_response = provider_response
            raise
        return provider_response, provider_request_id
    finally:
        if owns_client:
            await client.aclose()


async def dispatch_typesafe_jev(
    request: TypeSafeJevRequest,
    db: AsyncSession,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> TypeSafeJevResult:
    """Dry-run or execute one idempotent, no-retry Jev request under the pilot ceiling."""
    request_sha256 = _request_sha256(request)
    if request.pricing_contract != JEV_PRICING_CONTRACT or request.model != JEV_MODEL_ID:
        raise TypeSafeJevError("pricing_or_model_changed", "request does not match the pinned pilot contract")

    if request.dry_run:
        budget = await db.get(TypeSafeJevBudget, PILOT_BUDGET_KEY)
        if budget is None:
            raise TypeSafeJevError("budget_missing", "TypeSafe Jev pilot budget is not initialized", status_code=503)
        _assert_budget_contract(budget)
        return TypeSafeJevResult(
            request_id=request.request_id,
            request_sha256=request_sha256,
            status="dry_run",
            model_requested=request.model,
            pricing_contract=request.pricing_contract,
            budget=_budget_view(budget),
            sources=request.sources,
            rubric=request.rubric,
            observation=request.observation,
        )

    dispatch, budget, deduplicated = await _reserve(db, request, request_sha256)
    if deduplicated:
        return _result_from_dispatch(dispatch, budget, deduplicated=True)

    try:
        key = resolve_typesafe_api_key()
    except TypeSafeJevError as exc:
        current, budget = await _finalize_not_dispatched(db, dispatch, exc)
        return _result_from_dispatch(current, budget, deduplicated=False)
    provider_request_id: str | None = None
    try:
        try:
            provider_response, provider_request_id = await call_typesafe_jev(
                request,
                api_key=key,
                http_client=http_client,
            )
        except TypeSafeJevError as exc:
            if exc.provider_response is not None and exc.kind not in {
                "model_version_changed",
                "provider_contract_changed",
            }:
                current, budget = await _finalize_known(
                    db,
                    dispatch,
                    exc.provider_response,
                    provider_request_id=exc.provider_request_id,
                    validation_error=exc,
                )
            else:
                budget = await _mark_uncertain(
                    db,
                    dispatch,
                    kind=exc.kind,
                    detail=exc.detail,
                    provider_request_id=exc.provider_request_id,
                )
                current = await db.get(TypeSafeJevDispatch, dispatch.request_id)
                assert current is not None
            return _result_from_dispatch(current, budget, deduplicated=False)
        current, budget = await _finalize_known(
            db,
            dispatch,
            provider_response,
            provider_request_id=provider_request_id,
            validation_error=None,
        )
        return _result_from_dispatch(current, budget, deduplicated=False)
    except httpx.HTTPError:
        budget = await _mark_uncertain(
            db,
            dispatch,
            kind="transport_error",
            detail="TypeSafe transport failed after dispatch; billing is uncertain",
            provider_request_id=provider_request_id,
        )
        current = await db.get(TypeSafeJevDispatch, dispatch.request_id)
        assert current is not None
        return _result_from_dispatch(current, budget, deduplicated=False)


__all__ = [
    "JEV_INPUT_USD_PER_MILLION",
    "JEV_MAX_INPUT_TOKENS",
    "JEV_MODEL_ID",
    "JEV_PRICING_CONTRACT",
    "JEV_PRICING_SOURCE",
    "JEV_RESERVED_COST_USD",
    "PILOT_CEILING_USD",
    "TypeSafeJevError",
    "call_typesafe_jev",
    "dispatch_typesafe_jev",
    "resolve_typesafe_api_key",
]
