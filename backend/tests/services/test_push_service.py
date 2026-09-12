"""Exercise push scoping against an in-memory SQL store and a fake transport."""

import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from pywebpush import WebPushException
from sqlalchemy import Table, create_engine, select
from sqlalchemy.orm import Session

from app.models.push_subscription import PushSubscription
from app.services import push_service
from app.services.push_scope import PushScope

NERI = PushScope("neri", "neri-client")
SUMMITFLOW = PushScope("summitflow", "summitflow-client")


@pytest.fixture
def push_db(monkeypatch):
    monkeypatch.setattr(push_service, "settings", SimpleNamespace(
        vapid_private_key="fixture-only", vapid_subject="mailto:fixture@example.invalid",
        agent_hub_dashboard_client_id="fixture-dashboard",
    ))
    engine = create_engine("sqlite://")
    cast(Table, PushSubscription.__table__).create(engine)
    with Session(engine) as session:
        # Same persistence seam, using a synchronous in-memory store under async calls.
        db = SimpleNamespace(execute=AsyncMock(side_effect=session.execute),
                             commit=AsyncMock(side_effect=session.commit),
                             rollback=AsyncMock(side_effect=session.rollback))
        yield db, session
    engine.dispose()


async def register(db, scope=NERI, endpoint="https://push.invalid/neri", key="fixture-key"):
    return await push_service.save_subscription(db, endpoint, key, "fixture-auth", scope=scope)


@pytest.mark.asyncio
async def test_scoped_upsert_cannot_overwrite_another_application_or_owner(push_db) -> None:
    db, session = push_db
    first = await register(db)
    assert (await register(db))["id"] == first["id"]
    assert "endpoint" not in first
    for scope in (SUMMITFLOW, PushScope("neri", "another-owner")):
        with pytest.raises(ValueError, match="different application or owner"):
            await register(db, scope)
    await register(db, SUMMITFLOW, "https://push.invalid/summitflow")
    assert len(session.scalars(select(PushSubscription)).all()) == 2
    assert not await push_service.delete_subscription(db, "https://push.invalid/neri", scope=SUMMITFLOW)
    assert await push_service.delete_subscription(db, "https://push.invalid/neri", scope=NERI)


@pytest.mark.asyncio
async def test_legacy_requires_explicit_reregistration_with_its_keys(push_db) -> None:
    db, session = push_db
    session.add(PushSubscription(id="legacy", endpoint="https://push.invalid/legacy",
                                 p256dh_key="legacy-key", auth_key="fixture-auth"))
    session.commit()
    assert not await push_service.get_subscriptions(db, scope=NERI)
    assert not await push_service.get_subscriptions(db, scope=SUMMITFLOW)
    legacy_scope = PushScope("summitflow", "summitflow-client", include_legacy=True)
    assert len(await push_service.get_subscriptions(db, scope=legacy_scope)) == 1
    # Even an internally constructed non-SummitFlow scope cannot expand to legacy.
    assert not await push_service.get_subscriptions(db, scope=PushScope("neri", "neri-client", True))
    with pytest.raises(ValueError):
        await register(db, NERI, "https://push.invalid/legacy", "different-key")
    adopted = await register(db, NERI, "https://push.invalid/legacy", "legacy-key")
    assert adopted["id"] == "legacy"
    assert not await push_service.get_subscriptions(db, scope=legacy_scope)
    assert len(await push_service.get_subscriptions(db, scope=NERI)) == 1


@pytest.mark.asyncio
async def test_transport_only_receives_selected_application_payload(push_db) -> None:
    db, _ = push_db
    await register(db)
    await register(db, SUMMITFLOW, "https://push.invalid/summitflow")
    with (
        patch("app.services.push_service.is_configured", return_value=True),
        patch("app.services.push_service.webpush") as send,
    ):
        sent = await push_service.send_push(db, {"title": "Fixture", "body": "No real alert"}, scope=NERI)
    assert sent == 1
    assert send.call_count == 1
    assert send.call_args.kwargs["subscription_info"]["endpoint"] == "https://push.invalid/neri"
    payload = json.loads(send.call_args.kwargs["data"])
    assert payload == {"title": "Fixture", "body": "No real alert"}
    assert "fixture-key" not in send.call_args.kwargs["data"]


@pytest.mark.asyncio
async def test_expiry_cleanup_is_scoped_and_does_not_log_endpoint_keys(push_db, caplog) -> None:
    db, session = push_db
    await register(db)
    await register(db, SUMMITFLOW, "https://push.invalid/summitflow")
    failure = WebPushException("fixture-key https://push.invalid/neri", response=SimpleNamespace(status_code=410))
    with (
        patch("app.services.push_service.is_configured", return_value=True),
        patch("app.services.push_service.webpush", side_effect=failure),
    ):
        assert await push_service.send_push(db, {"title": "Fixture"}, scope=NERI) == 0
    assert len(session.scalars(select(PushSubscription)).all()) == 1
    assert len(await push_service.get_subscriptions(db, scope=SUMMITFLOW)) == 1
    assert "fixture-key" not in caplog.text
    assert "https://push.invalid" not in caplog.text


@pytest.mark.asyncio
async def test_expiry_does_not_delete_concurrent_key_rotation(push_db) -> None:
    db, session = push_db
    saved = await register(db)

    def rotate_then_expire(**_kwargs):
        row = session.get(PushSubscription, saved["id"])
        row.p256dh_key = "rotated-key"
        session.commit()
        raise WebPushException("expired old key", response=SimpleNamespace(status_code=410))

    with (
        patch("app.services.push_service.is_configured", return_value=True),
        patch("app.services.push_service.webpush", side_effect=rotate_then_expire),
    ):
        assert await push_service.send_push(db, {"title": "Fixture"}, scope=NERI) == 0
    assert session.get(PushSubscription, saved["id"]).p256dh_key == "rotated-key"
