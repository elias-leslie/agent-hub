"""Routes that cannot serve are skipped before any provider call."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.constants import catalog
from app.routing import availability
from app.routing.registry import (
    get_provider_for_model,
    is_workload_provider,
    list_credential_providers,
)
from app.services.model_runtime_health import classify_runtime_failure
from tests.model_ids import MODEL_CATALOG


@pytest.fixture
def inactive_minimax():
    minimax = next(e for e in MODEL_CATALOG if e.provider == "codex")
    entry = replace(minimax, id="minimax/MiniMax-M3", provider="minimax")
    catalog.INACTIVE_MODEL_CATALOG_BY_ID[entry.id] = entry
    yield entry
    catalog.INACTIVE_MODEL_CATALOG_BY_ID.pop(entry.id, None)


def test_provider_comes_from_catalog_or_explicit_prefix_never_name_guessing() -> None:
    assert get_provider_for_model("gemini-3.8-flash") == "gemini"
    assert get_provider_for_model("codex/not-yet-catalogued") == "codex"
    assert get_provider_for_model("gpt-something") == "unknown"
    assert get_provider_for_model("kimi-latest") == "unknown"


async def _reason(model: str) -> str:
    reason = await availability.route_unavailable_reason(model)
    assert reason is not None, model
    return reason


@pytest.mark.asyncio
async def test_inactive_and_uncatalogued_models_are_unavailable(inactive_minimax) -> None:
    assert get_provider_for_model(inactive_minimax.id) == "minimax"
    assert "inactive" in await _reason(inactive_minimax.id)
    assert "not in the model catalog" in await _reason("gpt-something")


def test_inactive_providers_still_accept_credentials(inactive_minimax) -> None:
    assert "minimax" in list_credential_providers()


def test_opencode_go_accepts_a_key_but_never_routes() -> None:
    assert "opencode-go" in list_credential_providers()
    assert not is_workload_provider("opencode-go")


@pytest.mark.asyncio
async def test_keyless_provider_and_signed_out_claude(monkeypatch) -> None:
    monkeypatch.setattr(availability, "get_env_api_key", lambda provider: None)
    assert "no credential" in await _reason("nvidia/glm-5.3")
    assert await availability.route_unavailable_reason("local/gemma4:12b-it-qat") is None

    async def signed_out() -> bool:
        return False

    monkeypatch.setattr(availability, "claude_cli_signed_in", signed_out)
    assert "not signed in" in await _reason("claude-sonnet-5-5")


@pytest.mark.parametrize(
    ("message", "status"),
    [
        ("Error code: 402 - insufficient balance", "quota_exhausted"),
        ("Error code: 403 - Kimi Code is not available for this subscription", "access_denied"),
    ],
)
def test_billing_and_entitlement_refusals_are_classified(message, status) -> None:
    assert classify_runtime_failure(RuntimeError(message)).provider_status == status
