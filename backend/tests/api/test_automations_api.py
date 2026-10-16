"""Authentication and owner isolation at the Automations HTTP seam."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.automations import validate_profile
from app.db import get_db
from app.main import app
from app.models import AutomationProfile, AutomationProjectPolicy


@pytest.mark.asyncio
async def test_new_profile_preview_rejects_past_one_time_schedule():
    definition = SimpleNamespace(
        workflow_key="agent-hub.session_cleanup", owner_project_id="agent-hub",
        config_schema={"type": "object"},
    )
    with patch("app.api.automations.service.get_definition", new_callable=AsyncMock, return_value=definition):
        result = await validate_profile({
            "project_id": "agent-hub", "workflow_key": "agent-hub.session_cleanup",
            "schedule_type": "at", "schedule_value": "2026-03-05T12:00:00Z",
        }, AsyncMock())
    assert result["valid"] is False
    assert "future" in result["errors"][0]


@pytest.mark.asyncio
async def test_existing_historical_one_time_profile_preview_remains_valid():
    profile = AutomationProfile(
        id="historical", project_id="agent-hub", workflow_key="agent-hub.session_cleanup",
        definition_version=1, label="Historical reminder", subject_id=None,
        schedule_type="at", schedule_value="2026-03-05T12:00:00Z",
        schedule_timezone="UTC", config={}, enabled=False, clock_owner="central",
        owner_gate_reasons=[], revision=2,
    )
    db = AsyncMock()
    db.get.return_value = profile
    definition = SimpleNamespace(
        workflow_key="agent-hub.session_cleanup", owner_project_id="agent-hub",
        config_schema={"type": "object"},
    )
    with patch("app.api.automations.service.get_definition", new_callable=AsyncMock, return_value=definition):
        result = await validate_profile({"id": "historical"}, db)
    assert result["valid"] is True


@pytest.mark.asyncio
async def test_automation_registry_requires_verified_internal_secret():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/automations/registry", headers={
            "X-Client-Id": "summitflow", "X-Request-Source": "test",
        })
    assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_owner_cannot_import_another_projects_profile():
    mock_db = AsyncMock()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db
    try:
        with patch("app.api.automations.require_service_client", new_callable=AsyncMock) as owner:
            owner.return_value = {
                "client_type": "service", "allowed_projects": '["summitflow"]',
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
                headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"},
            ) as client:
                response = await client.post("/api/automations/profiles/import", json={
                    "project_id": "portfolio-ai", "workflow_key": "portfolio-ai/jenny_weekly_price_check",
                    "source_ref": "portfolio:price_check", "schedule_type": "cron",
                    "schedule_value": "0 5 * * *", "schedule_timezone": "UTC", "enabled": True,
                })
        assert response.status_code == 403
        mock_db.execute.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_owner_import_preserves_cursor_gates_and_legacy_clock():
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    async def override_db():
        yield db

    definition = SimpleNamespace(
        workflow_key="portfolio-ai/jenny_weekly_price_check", owner_project_id="portfolio-ai",
        version=1, label="Weekly price check",
        config_schema={"type": "object", "additionalProperties": False},
    )
    app.dependency_overrides[get_db] = override_db
    try:
        with (
            patch("app.api.automations._require_project_owner", new_callable=AsyncMock),
            patch("app.services.automations.get_definition", new_callable=AsyncMock, return_value=definition),
            patch("app.api.automations._profile", new_callable=AsyncMock, return_value={"clock_owner": "legacy"}),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
                headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"},
            ) as client:
                response = await client.post("/api/automations/profiles/import", json={
                    "project_id": "portfolio-ai", "workflow_key": "portfolio-ai/jenny_weekly_price_check",
                    "source_ref": "portfolio:price_check", "schedule_type": "every",
                    "schedule_value": "300000", "schedule_timezone": "UTC",
                    "config": {}, "enabled": False,
                    "next_run_at": "2026-09-23T15:30:00Z",
                    "last_run_at": "2026-09-23T15:25:00Z",
                    "run_count": 7, "owner_gate_reasons": ["quiet_hours"],
                    "imported_unreviewed_count": 2,
                })
        assert response.status_code == 200
        row = next(call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], AutomationProfile))
        assert row.clock_owner == "legacy"
        assert row.next_run_at == datetime(2026, 9, 23, 15, 30, tzinfo=UTC)
        assert row.run_count == 7
        assert row.owner_gate_reasons == ["quiet_hours"]
        assert row.imported_unreviewed_count == 2
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cutover_requires_owner_fence_and_preserves_imported_cursor():
    row = AutomationProfile(
        id="profile-1", project_id="portfolio-ai", workflow_key="portfolio-ai/jenny_weekly_price_check",
        definition_version=1, label="Weekly price check", schedule_type="every",
        schedule_value="300000", schedule_timezone="UTC", config={},
        enabled=True, clock_owner="legacy", owner_gate_reasons=[],
        source_ref="portfolio:price_check", revision=3,
        imported_unreviewed_count=0,
    )
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=row))

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with (
            patch("app.api.automations._require_project_owner", new_callable=AsyncMock),
            patch("app.api.automations._profile", new_callable=AsyncMock, return_value={"clock_owner": "central"}),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
                headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"},
            ) as client:
                response = await client.post("/api/automations/profiles/profile-1/cutover", json={
                    "expected_revision": 3, "fence_receipt": "owner-fence-42",
                    "next_run_at": "2026-09-23T15:30:00Z",
                })
        assert response.status_code == 200
        assert row.clock_owner == "central"
        assert row.revision == 4
        assert row.next_run_at == datetime(2026, 9, 23, 15, 30, tzinfo=UTC)
        assert db.add.call_args.args[0].snapshot["fence_receipt"] == "owner-fence-42"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_jobinator_cutover_waits_for_shared_quota_policy_sync():
    row = AutomationProfile(
        id="profile-1", project_id="jobinator-4000",
        workflow_key="jobinator-4000/nightly_screen", definition_version=1,
        label="Nightly screen", schedule_type="cron", schedule_value="30 7 * * *",
        schedule_timezone="UTC", config={}, enabled=False, clock_owner="legacy",
        owner_gate_reasons=[], source_ref="hatchet:jobinator-nightly-screen", revision=1,
    )
    policy = AutomationProjectPolicy(
        project_id="jobinator-4000", enabled=False,
        config={"screening_cap": 200, "classification_cap": 40},
        revision=2, sync_revision=1,
    )
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=row))
    db.get.return_value = policy

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with patch("app.api.automations._require_project_owner", new_callable=AsyncMock):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
                headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"},
            ) as client:
                response = await client.post("/api/automations/profiles/profile-1/cutover", json={
                    "expected_revision": 1, "fence_receipt": "owner-fenced",
                })
        assert response.status_code == 409
        assert row.clock_owner == "legacy"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_policy_write_refreshes_server_timestamp_before_serializing():
    row = AutomationProjectPolicy(
        project_id="summitflow", enabled=True, config={}, revision=2,
        sync_revision=0,
    )
    db = AsyncMock()

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with patch("app.api.automations.service.update_policy", new_callable=AsyncMock, return_value=row):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test",
                headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"},
            ) as client:
                response = await client.put("/api/automations/projects/summitflow/policy", json={
                    "expected_revision": 1, "enabled": True, "config": {},
                })
        assert response.status_code == 200
        db.refresh.assert_awaited_once_with(row)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_validation_errors_are_fixed_messages_not_exception_text():
    db = AsyncMock()
    db.get.return_value = None
    assert (await validate_profile({"id": "nope"}, db))["errors"] == ["unknown profile"]
    assert (await validate_profile({}, AsyncMock()))["errors"] == ["workflow_key is required"]
    with patch("app.api.automations.service.get_definition", new_callable=AsyncMock, side_effect=KeyError("x")):
        result = await validate_profile({"workflow_key": "missing.workflow"}, AsyncMock())
    assert result == {"valid": False, "normalized": None, "errors": ["unknown workflow"]}
