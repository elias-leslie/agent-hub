"""Writer identity: the middleware names who made each change (owner, agent session, client)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.request_actor import (
    classify_request_writer,
    current_request_writer,
    parse_writer_header,
    writer_columns,
)

LANE = "delivery=9241d1751b8daaac; session=aico-widget-a36fa317"


def test_header_parts_are_read_and_cleaned() -> None:
    assert parse_writer_header(LANE) == ("9241d1751b8daaac", "aico-widget-a36fa317")
    assert parse_writer_header("session=aico-widget-1") == (None, "aico-widget-1")
    assert parse_writer_header("delivery=abc;'drop table; session= x y ") == ("abc", "xy")
    assert parse_writer_header(None) == (None, None)


@pytest.mark.parametrize(
    ("header", "owner", "dashboard", "kind"),
    [
        (LANE, False, False, "agent"),
        (None, False, True, "owner"),  # the dashboard
        (None, True, False, "owner"),  # the owner token
        (LANE, True, False, "owner"),
        (LANE, False, True, "agent"),  # an agent session using the internal secret is still an agent
        (None, False, False, "client"),
    ],
)
def test_classification(header: str | None, owner: bool, dashboard: bool, kind: str) -> None:
    assert classify_request_writer(writer_header=header, owner=owner, dashboard=dashboard).kind == kind


def test_outside_a_request_the_writer_is_system() -> None:
    assert writer_columns() == {"writer_kind": "system", "writer_delivery": None, "writer_session": None}


def _whoami_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.middleware import access_control_paths
    from app.middleware.access_control import AccessControlMiddleware

    monkeypatch.setattr(access_control_paths.settings, "internal_service_secret", "s3cret")
    inner = FastAPI()

    @inner.put("/api/whoami")
    async def whoami() -> dict[str, str | None]:
        writer = current_request_writer()
        return {"kind": writer.kind, "delivery": writer.delivery, "session": writer.session}

    inner.add_middleware(AccessControlMiddleware)
    return TestClient(inner)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (  # st memory update --scope from a lane: internal secret plus the writer header
            {"X-Agent-Hub-Internal": "s3cret", "X-Client-Id": "c1", "X-Request-Source": "st-memory", "X-Context-Writer": LANE},
            {"kind": "agent", "delivery": "9241d1751b8daaac", "session": "aico-widget-a36fa317"},
        ),
        (  # the dashboard proxy
            {"X-Agent-Hub-Internal": "s3cret", "X-Client-Id": "agent-hub-dashboard", "X-Request-Source": "agent-hub-dashboard"},
            {"kind": "owner", "delivery": None, "session": None},
        ),
        (  # another internal caller that is not the dashboard
            {"X-Agent-Hub-Internal": "s3cret", "X-Client-Id": "c1", "X-Request-Source": "st-memory"},
            {"kind": "client", "delivery": None, "session": None},
        ),
    ],
)
def test_middleware_binds_the_writer_for_the_endpoint(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str], expected: dict[str, str | None]
) -> None:
    with patch("app.middleware.access_control.schedule_ui_request_log"):
        response = _whoami_client(monkeypatch).put("/api/whoami", headers=headers)
    assert response.json() == expected


def test_owner_token_makes_the_owner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.core import access_identity

    token = tmp_path / "owner-token"
    token.write_text("owner-secret\n")
    monkeypatch.setattr(access_identity.settings, "agent_hub_owner_token_file", str(token))
    headers = {"X-Agent-Hub-Internal": "s3cret", "X-Client-Id": "c1", "X-Request-Source": "st-memory",
               "X-Agent-Hub-Owner-Token": "owner-secret"}
    with patch("app.middleware.access_control.schedule_ui_request_log"):
        response = _whoami_client(monkeypatch).put("/api/whoami", headers=headers)
    assert response.json()["kind"] == "owner"


async def test_writers_stay_raw_until_context_deliveries_exists() -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from app.services.context_writer import resolve_writers

    db = AsyncMock()
    db.execute.return_value = MagicMock(**{"scalar.return_value": False})
    revision = SimpleNamespace(writer_kind="agent", writer_delivery="h1", writer_session="aico-widget-1")

    (writer,) = await resolve_writers(db, [revision])

    assert (writer.kind, writer.session, writer.delivery, writer.harness, writer.resolved) == (
        "agent", "aico-widget-1", "h1", None, False)
    assert db.execute.await_count == 1  # only the existence check
