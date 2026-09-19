from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.api.typesafe_jev_schemas import (
    ChoiceQuestion,
    ObservationProvenance,
    RubricProvenance,
    ScoreQuestion,
    SourceProvenance,
    TypeSafeJevRequest,
    TypeSafeProviderResponse,
)
from app.models.typesafe_jev import TypeSafeJevBudget, TypeSafeJevDispatch
from app.services.typesafe_jev import (
    JEV_PRICING_CONTRACT,
    JEV_RESERVED_COST_USD,
    PILOT_BUDGET_KEY,
    PILOT_CEILING_USD,
    TypeSafeJevError,
    _finalize_known,
    _load_key_file,
    _request_sha256,
    call_typesafe_jev,
    dispatch_typesafe_jev,
)


def _request(*, dry_run: bool = False) -> TypeSafeJevRequest:
    return TypeSafeJevRequest(
        request_id=uuid4(),
        state={"review": "sanitized candidate"},
        questions={
            "decision": {
                "type": "choice",
                "instructions": "Choose the supported assessment.",
                "criteria": {"supported": "Supported", "unsupported": "Unsupported"},
            }
        },
        sources=[
            SourceProvenance(
                source_id="case-1",
                revision="v1",
                content_sha256="a" * 64,
            )
        ],
        rubric=RubricProvenance(
            rubric_id="review-v1",
            revision="v1",
            rubric_sha256="b" * 64,
        ),
        dry_run=dry_run,
    )


@pytest.mark.asyncio
async def test_typed_client_sends_only_provider_fields_once() -> None:
    calls: list[dict[str, object]] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        calls.append(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            headers={"x-typesafe-request-id": "provider-request-1"},
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "decision": {
                        "type": "choice",
                        "choice": "supported",
                        "probabilities": {"supported": 0.8, "unsupported": 0.2},
                        "confidence": 0.8,
                    }
                },
                "usage": {"input_tokens": 321, "output_tokens": 0},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        response, provider_request_id = await call_typesafe_jev(
            _request(), api_key="test-key", http_client=client
        )

    assert provider_request_id == "provider-request-1"
    assert response.usage.input_tokens == 321
    assert len(calls) == 1
    assert set(calls[0]) == {"state", "model", "questions"}
    assert calls[0]["model"] == "jev-1.13.0"


@pytest.mark.asyncio
async def test_typed_client_fails_visibly_on_model_version_change() -> None:
    async def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-typesafe-request-id": "provider-request-2"},
            json={
                "model": "jev-1.14.0",
                "answers": {
                    "decision": {
                        "type": "choice",
                        "choice": "supported",
                        "probabilities": {"supported": 0.8, "unsupported": 0.2},
                        "confidence": 0.8,
                    }
                },
                "usage": {"input_tokens": 400, "output_tokens": 0},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(TypeSafeJevError) as caught:
            await call_typesafe_jev(_request(), api_key="test-key", http_client=client)

    assert caught.value.kind == "model_version_changed"
    assert caught.value.provider_request_id == "provider-request-2"
    assert caught.value.provider_response is not None
    assert caught.value.provider_response.usage.input_tokens == 400


@pytest.mark.parametrize("count", [1, 256])
def test_choice_cardinality_matches_provider_contract(count: int) -> None:
    with pytest.raises(ValidationError):
        ChoiceQuestion(type="choice", instructions="choose", criteria={str(i): i for i in range(count)})


@pytest.mark.parametrize("count", [1, 11])
def test_score_cardinality_matches_provider_contract(count: int) -> None:
    with pytest.raises(ValidationError):
        ScoreQuestion(type="score", instructions="score", criteria=list(range(count)))


def test_key_file_requires_owner_only_permissions(tmp_path: Path) -> None:
    key_file = tmp_path / "credentials.env"
    key_file.write_text("TYPESAFE_API_KEY=test-value\n", encoding="utf-8")
    key_file.chmod(0o600)
    assert _load_key_file(key_file) == "test-value"

    key_file.chmod(0o644)
    with pytest.raises(TypeSafeJevError, match="mode 0600"):
        _load_key_file(key_file)


@pytest.mark.asyncio
async def test_dry_run_reports_full_contract_reservation_without_dispatch() -> None:
    budget = TypeSafeJevBudget(
        key=PILOT_BUDGET_KEY,
        ceiling_usd=PILOT_CEILING_USD,
        spent_usd=Decimal("0"),
        reserved_usd=Decimal("0"),
        model_id="jev-1.13.0",
        pricing_contract=JEV_PRICING_CONTRACT,
    )
    db = AsyncMock()
    db.get.return_value = budget

    result = await dispatch_typesafe_jev(_request(dry_run=True), db)

    assert result.status == "dry_run"
    assert result.budget.ceiling_usd == "5.000000000"
    assert result.budget.reservation_usd == f"{JEV_RESERVED_COST_USD:.9f}"
    db.commit.assert_not_awaited()


def test_request_identity_invalidates_on_provenance_and_deliberate_repeat() -> None:
    original = _request()
    source_changed = original.model_copy(
        update={
            "sources": [
                SourceProvenance(
                    source_id="case-1",
                    revision="v2",
                    content_sha256="c" * 64,
                )
            ]
        }
    )
    rubric_changed = original.model_copy(
        update={
            "rubric": RubricProvenance(
                rubric_id="review-v1",
                revision="v2",
                rubric_sha256="d" * 64,
            )
        }
    )
    repeated = original.model_copy(
        update={
            "observation": ObservationProvenance(
                series_id="variability-check",
                ordinal=2,
                purpose="Independent variability observation",
            )
        }
    )

    identities = {
        _request_sha256(original),
        _request_sha256(source_changed),
        _request_sha256(rubric_changed),
        _request_sha256(repeated),
    }
    assert len(identities) == 4


@pytest.mark.asyncio
async def test_identical_actual_request_is_cache_hit_without_key_or_spend(monkeypatch) -> None:
    request = _request()
    budget = TypeSafeJevBudget(
        key=PILOT_BUDGET_KEY,
        ceiling_usd=PILOT_CEILING_USD,
        spent_usd=Decimal("0.000001000"),
        reserved_usd=Decimal("0"),
        model_id="jev-1.13.0",
        pricing_contract=JEV_PRICING_CONTRACT,
    )
    existing = TypeSafeJevDispatch(
        request_id=str(uuid4()),
        budget_key=PILOT_BUDGET_KEY,
        request_sha256=_request_sha256(request),
        status="failed",
        model_requested="jev-1.13.0",
        pricing_contract=JEV_PRICING_CONTRACT,
        reserved_input_tokens=64_000,
        reserved_cost_usd=JEV_RESERVED_COST_USD,
        source_provenance=[source.model_dump(mode="json") for source in request.sources],
        rubric_provenance=request.rubric.model_dump(mode="json"),
        observation_provenance=None,
        error_kind="unsupported_output",
        error_detail="prior known result",
    )
    db = AsyncMock()
    db.scalar.return_value = budget
    db.get.return_value = existing
    monkeypatch.setattr(
        "app.services.typesafe_jev.resolve_typesafe_api_key",
        lambda: pytest.fail("cache hit must not load a credential"),
    )

    result = await dispatch_typesafe_jev(request, db)

    assert result.deduplicated is True
    assert str(result.request_id) == existing.request_id
    assert budget.spent_usd == Decimal("0.000001000")
    db.commit.assert_not_awaited()


def _provider_response(*, model: str = "jev-1.13.0") -> TypeSafeProviderResponse:
    return TypeSafeProviderResponse.model_validate(
        {
            "model": model,
            "answers": {
                "decision": {
                    "type": "choice",
                    "choice": "supported",
                    "probabilities": {"supported": 0.8, "unsupported": 0.2},
                    "confidence": 0.8,
                }
            },
            "usage": {"input_tokens": 400, "output_tokens": 0},
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["model_version_changed", "provider_contract_changed"])
async def test_untrusted_contract_response_retains_reservation(monkeypatch, kind: str) -> None:
    request = _request()
    dispatch = AsyncMock(spec=TypeSafeJevDispatch)
    dispatch.request_id = str(request.request_id)
    budget = AsyncMock(spec=TypeSafeJevBudget)
    response = _provider_response(model="jev-1.14.0")
    error = TypeSafeJevError(
        kind,
        "contract changed",
        status_code=502,
        provider_request_id="provider-request-3",
        provider_response=response,
    )
    monkeypatch.setattr(
        "app.services.typesafe_jev._reserve",
        AsyncMock(return_value=(dispatch, budget, False)),
    )
    monkeypatch.setattr("app.services.typesafe_jev.resolve_typesafe_api_key", lambda: "test-key")
    monkeypatch.setattr("app.services.typesafe_jev.call_typesafe_jev", AsyncMock(side_effect=error))
    mark_uncertain = AsyncMock(return_value=budget)
    monkeypatch.setattr("app.services.typesafe_jev._mark_uncertain", mark_uncertain)
    finalize_known = AsyncMock()
    monkeypatch.setattr("app.services.typesafe_jev._finalize_known", finalize_known)
    db = AsyncMock()
    db.get.return_value = dispatch
    monkeypatch.setattr(
        "app.services.typesafe_jev._result_from_dispatch",
        lambda *_args, **_kwargs: "result",
    )

    result = await dispatch_typesafe_jev(request, db)

    assert result == "result"
    mark_uncertain.assert_awaited_once()
    finalize_known.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_key_is_recorded_as_not_dispatched(monkeypatch) -> None:
    request = _request()
    dispatch = AsyncMock(spec=TypeSafeJevDispatch)
    budget = AsyncMock(spec=TypeSafeJevBudget)
    credential_error = TypeSafeJevError("credential_unavailable", "missing")
    monkeypatch.setattr(
        "app.services.typesafe_jev._reserve",
        AsyncMock(return_value=(dispatch, budget, False)),
    )
    monkeypatch.setattr(
        "app.services.typesafe_jev.resolve_typesafe_api_key",
        lambda: (_ for _ in ()).throw(credential_error),
    )
    finalize = AsyncMock(return_value=(dispatch, budget))
    monkeypatch.setattr("app.services.typesafe_jev._finalize_not_dispatched", finalize)
    monkeypatch.setattr(
        "app.services.typesafe_jev._result_from_dispatch",
        lambda *_args, **_kwargs: "result",
    )

    result = await dispatch_typesafe_jev(request, AsyncMock())

    assert result == "result"
    finalize.assert_awaited_once_with(ANY, dispatch, credential_error)


@pytest.mark.asyncio
async def test_finalize_refreshes_locked_budget_before_accounting(monkeypatch) -> None:
    """A provider wait must not let a stale identity-map value erase concurrent spend."""
    stale = TypeSafeJevBudget(
        key=PILOT_BUDGET_KEY,
        ceiling_usd=PILOT_CEILING_USD,
        spent_usd=Decimal("0"),
        reserved_usd=JEV_RESERVED_COST_USD,
        model_id="jev-1.13.0",
        pricing_contract=JEV_PRICING_CONTRACT,
    )
    refreshed = TypeSafeJevBudget(
        key=PILOT_BUDGET_KEY,
        ceiling_usd=PILOT_CEILING_USD,
        spent_usd=Decimal("0.001000000"),
        reserved_usd=JEV_RESERVED_COST_USD * 2,
        model_id="jev-1.13.0",
        pricing_contract=JEV_PRICING_CONTRACT,
    )
    current = TypeSafeJevDispatch(
        request_id=str(uuid4()),
        budget_key=PILOT_BUDGET_KEY,
        request_sha256="e" * 64,
        status="reserved",
        model_requested="jev-1.13.0",
        pricing_contract=JEV_PRICING_CONTRACT,
        reserved_input_tokens=64_000,
        reserved_cost_usd=JEV_RESERVED_COST_USD,
        source_provenance=[],
        rubric_provenance={},
    )
    db = AsyncMock()

    async def scalar(statement):
        if statement.get_execution_options().get("populate_existing"):
            return refreshed
        return stale

    db.scalar.side_effect = scalar
    monkeypatch.setattr(
        "app.services.typesafe_jev._locked_dispatch",
        AsyncMock(return_value=current),
    )

    _, budget = await _finalize_known(
        db,
        current,
        _provider_response(),
        provider_request_id="provider-request-4",
        validation_error=None,
    )

    assert budget is refreshed
    assert budget.spent_usd == Decimal("0.001016800")
    assert budget.reserved_usd == JEV_RESERVED_COST_USD
    db.commit.assert_awaited_once()
