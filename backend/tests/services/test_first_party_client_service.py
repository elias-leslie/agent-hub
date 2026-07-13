"""Tests for first-party client reconciliation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.sql import Select

from app.models import Client
from app.services.first_party_client_service import reconcile_first_party_clients


def _result_for(client: Client | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = client
    return result


def _client_id_for_stmt(stmt: Select[tuple[Client]]) -> str:
    compiled = stmt.compile()
    return str(compiled.params["id_1"])


def _mock_db(existing_clients: dict[str, Client]) -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    async def execute(stmt: Select[tuple[Client]]) -> MagicMock:
        return _result_for(existing_clients.get(_client_id_for_stmt(stmt)))

    mock_db.execute.side_effect = execute
    return mock_db


class TestReconcileFirstPartyClients:
    @pytest.mark.asyncio
    async def test_creates_canonical_clients_and_custom_aliases(self) -> None:
        mock_db = _mock_db({})

        with (
            patch(
                "app.services.first_party_client_service.settings.agent_hub_dashboard_client_id",
                "dashboard-client",
            ),
            patch(
                "app.services.first_party_client_service.settings.summitflow_client_id",
                "summit-custom",
            ),
            patch(
                "app.services.first_party_client_service.settings.portfolio_client_id",
                "portfolio-client",
            ),
            patch(
                "app.services.first_party_client_service.settings.monkey_fight_client_id",
                "",
            ),
            patch(
                "app.services.first_party_client_service.invalidate_client_cache"
            ) as mock_invalidate_client_cache,
        ):
            changed = await reconcile_first_party_clients(mock_db)

        assert changed == [
            "dashboard-client",
            "agent-hub-telegram-bot",
            "summitflow",
            "portfolio-ai",
            "monkey-fight",
            "summit-custom",
            "portfolio-client",
            "hermes",
        ]
        assert mock_db.add.call_count == 8
        created_clients = [call.args[0] for call in mock_db.add.call_args_list]
        assert [client.id for client in created_clients] == changed
        assert [client.display_name for client in created_clients] == [
            "agent-hub-dashboard",
            "agent-hub-telegram-bot",
            "summitflow",
            "portfolio-ai",
            "monkey-fight",
            "summitflow",
            "portfolio-ai",
            "hermes",
        ]
        assert [client.client_type for client in created_clients] == [
            "internal",
            "internal",
            "internal",
            "internal",
            "external",
            "internal",
            "internal",
            "external",
        ]
        assert [client.allowed_projects for client in created_clients] == [
            '["agent-hub"]',
            '["agent-hub"]',
            '["summitflow", "agent-hub"]',
            '["portfolio-ai"]',
            '["monkey-fight"]',
            '["summitflow", "agent-hub"]',
            '["portfolio-ai"]',
            None,
        ]
        mock_db.commit.assert_awaited_once()
        assert mock_invalidate_client_cache.call_count == len(changed)

    @pytest.mark.asyncio
    async def test_updates_existing_canonical_client_without_resetting_status(self) -> None:
        existing = Client(
            id="portfolio-ai",
            display_name="Old Portfolio",
            client_type="external",
            status="blocked",
            allowed_projects='["wrong-project"]',
        )
        mock_db = _mock_db({"portfolio-ai": existing})

        with (
            patch(
                "app.services.first_party_client_service.settings.agent_hub_dashboard_client_id",
                "",
            ),
            patch(
                "app.services.first_party_client_service.settings.portfolio_client_id",
                "",
            ),
            patch(
                "app.services.first_party_client_service.settings.summitflow_client_id",
                "",
            ),
            patch(
                "app.services.first_party_client_service.settings.monkey_fight_client_id",
                "",
            ),
            patch(
                "app.services.first_party_client_service.invalidate_client_cache"
            ) as mock_invalidate_client_cache,
        ):
            changed = await reconcile_first_party_clients(mock_db)

        assert changed == [
            "agent-hub-telegram-bot",
            "summitflow",
            "portfolio-ai",
            "monkey-fight",
            "hermes",
        ]
        assert existing.display_name == "portfolio-ai"
        assert existing.client_type == "internal"
        assert existing.status == "blocked"
        assert existing.allowed_projects == '["portfolio-ai"]'
        created_clients = [call.args[0].id for call in mock_db.add.call_args_list]
        assert created_clients == [
            "agent-hub-telegram-bot",
            "summitflow",
            "monkey-fight",
            "hermes",
        ]
        mock_db.commit.assert_awaited_once()
        assert mock_invalidate_client_cache.call_count == 5
        mock_invalidate_client_cache.assert_any_call("portfolio-ai")

    @pytest.mark.asyncio
    async def test_seeds_canonical_clients_when_custom_ids_are_blank(self) -> None:
        mock_db = _mock_db({})

        with (
            patch(
                "app.services.first_party_client_service.settings.agent_hub_dashboard_client_id",
                "",
            ),
            patch(
                "app.services.first_party_client_service.settings.portfolio_client_id",
                "",
            ),
            patch(
                "app.services.first_party_client_service.settings.summitflow_client_id",
                "",
            ),
            patch(
                "app.services.first_party_client_service.settings.monkey_fight_client_id",
                "",
            ),
            patch(
                "app.services.first_party_client_service.invalidate_client_cache"
            ) as mock_invalidate_client_cache,
        ):
            changed = await reconcile_first_party_clients(mock_db)

        assert changed == [
            "agent-hub-telegram-bot",
            "summitflow",
            "portfolio-ai",
            "monkey-fight",
            "hermes",
        ]
        created_clients = [call.args[0].id for call in mock_db.add.call_args_list]
        assert created_clients == changed
        mock_db.commit.assert_awaited_once()
        assert mock_invalidate_client_cache.call_count == len(changed)
