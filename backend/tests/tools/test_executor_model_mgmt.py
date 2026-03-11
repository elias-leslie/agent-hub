"""Tests for _executor_model_mgmt alias handling."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.tools._executor_model_mgmt import get_model_details, update_agent_model


def _mock_async_session(mock_db: AsyncMock):
    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session


@pytest.mark.anyio
async def test_get_model_details_resolves_explicit_catalog_aliases() -> None:
    mock_db = AsyncMock()

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.model_enrichment_service.get_all_enrichments",
            new_callable=AsyncMock,
            return_value={},
        ),
    ):
        result = await get_model_details("codex-5.2")

    assert "# " in result
    assert "codex/gpt-5.2-codex" in result


@pytest.mark.anyio
async def test_update_agent_model_normalizes_explicit_alias_inputs() -> None:
    mock_db = AsyncMock()
    updated = SimpleNamespace(version=7)

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.agent_service.get_agent_service",
        ) as mock_get_service,
    ):
        service = mock_get_service.return_value
        service.get_by_slug = AsyncMock(return_value=SimpleNamespace(id="agent-1"))
        service.update = AsyncMock(return_value=updated)

        result = await update_agent_model(
            agent_slug="persona",
            primary_model_id="codex-5.2",
            fallback_models=["codex/gpt-5.4", "openai/gpt-5.2"],
            escalation_model_id="claude-sonnet-4-6",
            temperature=None,
            thinking_level=None,
            change_reason="normalize aliases",
        )

    assert "codex/gpt-5.2-codex" in result
    service.update.assert_awaited_once()
    kwargs = service.update.await_args.kwargs
    assert kwargs["primary_model_id"] == "codex/gpt-5.2-codex"
    assert kwargs["fallback_models"] == ["codex/gpt-5.4", "openai/gpt-5.2"]
    assert kwargs["escalation_model_id"] == "claude-sonnet-4-6"


@pytest.mark.anyio
async def test_update_agent_model_preserves_distinct_prefixed_model_ids() -> None:
    mock_db = AsyncMock()
    updated = SimpleNamespace(version=8)

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.agent_service.get_agent_service",
        ) as mock_get_service,
    ):
        service = mock_get_service.return_value
        service.get_by_slug = AsyncMock(return_value=SimpleNamespace(id="agent-1"))
        service.update = AsyncMock(return_value=updated)

        result = await update_agent_model(
            agent_slug="persona",
            primary_model_id="codex/gpt-5.2",
            fallback_models=None,
            escalation_model_id=None,
            temperature=None,
            thinking_level=None,
            change_reason="preserve distinct ids",
        )

    assert "primary_model=codex/gpt-5.2" in result
    kwargs = service.update.await_args.kwargs
    assert kwargs["primary_model_id"] == "codex/gpt-5.2"
