"""Tests for first-party client reconciliation (insert-only)."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import Client
from app.services.first_party_client_service import reconcile_first_party_clients

_SETTINGS = "app.services.first_party_client_service.settings"


def _mock_db(existing_clients: dict[str, Client]) -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    async def get(model: type[Client], client_id: str) -> Client | None:
        return existing_clients.get(client_id)

    mock_db.get.side_effect = get
    return mock_db


def _configured(stack: ExitStack, **ids: str) -> MagicMock:
    for name in ("agent_hub_dashboard_client_id", "summitflow_client_id", "portfolio_client_id", "monkey_fight_client_id"):
        stack.enter_context(patch(f"{_SETTINGS}.{name}", ids.get(name, "")))
    return stack.enter_context(patch("app.services.first_party_client_service.invalidate_client_cache"))


class TestReconcileFirstPartyClients:
    @pytest.mark.asyncio
    async def test_creates_configured_clients_only(self) -> None:
        mock_db = _mock_db({})
        with ExitStack() as stack:
            invalidate = _configured(
                stack, agent_hub_dashboard_client_id="dashboard-client",
                summitflow_client_id="summit-custom", portfolio_client_id="portfolio-client",
            )
            changed = await reconcile_first_party_clients(mock_db)

        # No guessable literal ids ("summitflow", "portfolio-ai", "monkey-fight") are seeded.
        assert changed == ["dashboard-client", "summit-custom", "portfolio-client"]
        created = [call.args[0] for call in mock_db.add.call_args_list]
        assert [(c.id, c.display_name, c.client_type, c.allowed_projects) for c in created] == [
            ("dashboard-client", "agent-hub-dashboard", "internal", '["agent-hub"]'),
            ("summit-custom", "summitflow", "internal", '["summitflow", "agent-hub"]'),
            ("portfolio-client", "portfolio-ai", "internal", '["portfolio-ai"]'),
        ]
        assert all(c.status == "active" for c in created)
        mock_db.commit.assert_awaited_once()
        assert invalidate.call_count == 3

    @pytest.mark.asyncio
    async def test_never_rewrites_an_existing_registration(self) -> None:
        # The owner narrowed this client in the dashboard; a restart must not widen it back.
        existing = Client(
            id="portfolio-client", display_name="Portfolio (narrowed)", client_type="service",
            status="blocked", allowed_projects="[]",
        )
        mock_db = _mock_db({"portfolio-client": existing})
        with ExitStack() as stack:
            invalidate = _configured(stack, portfolio_client_id="portfolio-client")
            changed = await reconcile_first_party_clients(mock_db)

        assert changed == []
        assert (existing.display_name, existing.client_type, existing.status, existing.allowed_projects) == (
            "Portfolio (narrowed)", "service", "blocked", "[]",
        )
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_awaited()
        invalidate.assert_not_called()
