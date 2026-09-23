"""Owner receipt identities are seeded without changing existing clients."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.first_party_client_service import seed_automation_owner_clients


@pytest.mark.asyncio
async def test_seed_only_adds_missing_owner_identity():
    db = AsyncMock()
    db.add = MagicMock()
    db.get.side_effect = [object(), object(), None]
    with (
        patch("app.services.first_party_client_service.settings.portfolio_client_id", "portfolio-id"),
        patch("app.services.first_party_client_service.settings.jobinator_client_id", "jobinator-id"),
        patch("app.services.first_party_client_service.settings.neri_client_id", "neri-id"),
    ):
        inserted = await seed_automation_owner_clients(db)

    assert inserted == ["neri"]
    db.add.assert_called_once()
    client = db.add.call_args.args[0]
    assert client.id == "neri-id"
    assert client.allowed_projects == '["neri"]'
    db.commit.assert_awaited_once()
