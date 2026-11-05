"""Bounded context exports use the service identity and retain JSON text verbatim."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from app.api.context_export import router
from app.db import get_db

HEADERS = {"X-Agent-Hub-Internal": "agent-hub-internal-v1", "X-Client-Id": "fixture-service"}


class _Result:
    def __init__(self, rows: list[str]) -> None:
        self.rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[str]:
        return self.rows


class _Session:
    def __init__(self, rows: list[str] | None = None) -> None:
        self.rows = rows or []
        self.statements: list[tuple[Any, dict[str, Any]]] = []
        self.failure: Exception | None = None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _Result:
        self.statements.append((statement, params or {}))
        if str(statement) == "SET TRANSACTION READ ONLY":
            return _Result([])
        if self.failure:
            raise self.failure
        assert params is not None
        return _Result(self.rows[params["offset"]:params["offset"] + params["fetch_limit"]])


@pytest.fixture
def db() -> _Session:
    return _Session()


@pytest.fixture
def registered_client(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    lookup = AsyncMock(return_value={"id": "fixture-service", "status": "active"})
    monkeypatch.setattr("app.middleware.access_control_auth.get_cached_client", lookup)
    return lookup


@pytest_asyncio.fixture
async def client(db: _Session, registered_client: AsyncMock) -> AsyncGenerator[AsyncClient]:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def test_export_is_registered_outside_admin_routes() -> None:
    from app.main import app

    assert "/api/context-export/{collection}" in {route.path for route in app.routes if hasattr(route, "path")}


@pytest.mark.parametrize("headers,status", [
    ({}, 401),
    ({"X-Client-Id": "fixture-service"}, 401),
    ({"X-Agent-Hub-Internal": "wrong", "X-Client-Id": "fixture-service"}, 401),
    ({"X-Agent-Hub-Internal": "agent-hub-internal-v1"}, 401),
])
async def test_export_refuses_missing_verified_service_identity(
    client: AsyncClient, db: _Session, registered_client: AsyncMock, headers: dict[str, str], status: int,
) -> None:
    response = await client.get("/api/context-export/memories", headers=headers)
    assert response.status_code == status
    assert db.statements == []
    registered_client.assert_not_awaited()


@pytest.mark.parametrize("identity", [None, {"status": "suspended"}, {"status": "pending"}])
async def test_export_refuses_unregistered_or_inactive_service(
    client: AsyncClient, db: _Session, registered_client: AsyncMock, identity: Any,
) -> None:
    registered_client.return_value = identity
    response = await client.get("/api/context-export/memories", headers=HEADERS)
    assert response.status_code == 403
    assert db.statements == []


async def test_export_pages_verbatim_rows_and_only_returns_a_next_offset_when_more_exist(
    client: AsyncClient, db: _Session, registered_client: AsyncMock,
) -> None:
    db.rows = ['{"id":1, "content":"fixture A"}', '{"id":2,"content":"fixture B"}', '{"id":3}']
    first = await client.get("/api/context-export/memories", params={"limit": 2}, headers=HEADERS)
    assert first.status_code == 200
    assert first.json() == {"rows": db.rows[:2], "next_offset": 2}
    second = await client.get("/api/context-export/memories", params={"offset": 2, "limit": 2}, headers=HEADERS)
    assert second.json() == {"rows": db.rows[2:], "next_offset": None}
    empty = await client.get("/api/context-export/memories", params={"offset": 3, "limit": 2}, headers=HEADERS)
    assert empty.json() == {"rows": [], "next_offset": None}
    assert str(db.statements[0][0]) == "SET TRANSACTION READ ONLY"
    assert db.statements[1][1] == {"offset": 0, "fetch_limit": 3}
    registered_client.assert_awaited_with("fixture-service")


async def test_default_page_never_returns_more_than_one_thousand_rows(client: AsyncClient, db: _Session) -> None:
    db.rows = [f'{{"id":{number}}}' for number in range(1001)]
    response = await client.get("/api/context-export/memories", headers=HEADERS)
    assert response.json() == {"rows": db.rows[:1000], "next_offset": 1000}


@pytest.mark.parametrize("collection,order", [
    ("memories", "ORDER BY id"), ("memory_settings", "ORDER BY id"),
    ("prompts", "ORDER BY id"), ("budgets", "ORDER BY harness, role"),
    ("project_rows", "ORDER BY id"), ("project_hash", "ORDER BY id"),
])
async def test_only_server_owned_queries_are_paged(
    client: AsyncClient, db: _Session, collection: str, order: str,
) -> None:
    response = await client.get(f"/api/context-export/{collection}", params={"limit": 1000}, headers=HEADERS)
    assert response.status_code == 200
    assert str(db.statements[0][0]) == "SET TRANSACTION READ ONLY"
    assert order in str(db.statements[1][0])
    assert db.statements[1][1] == {"offset": 0, "fetch_limit": 1001}


@pytest.mark.parametrize("params", [{"offset": -1}, {"limit": 0}, {"limit": 1001}])
async def test_page_bounds_are_validated_before_reading(client: AsyncClient, db: _Session, params: dict[str, int]) -> None:
    response = await client.get("/api/context-export/memories", params=params, headers=HEADERS)
    assert response.status_code == 422
    assert db.statements == []


async def test_unknown_collection_is_rejected_without_sql(client: AsyncClient, db: _Session) -> None:
    response = await client.get("/api/context-export/clients", headers=HEADERS)
    assert response.status_code == 404
    assert db.statements == []


async def test_agent_roles_are_explicit_validated_and_bound_as_parameters(client: AsyncClient, db: _Session) -> None:
    response = await client.get("/api/context-export/agents", params=[("agent_role", "fixture-role"), ("agent_role", "other-role")], headers=HEADERS)
    assert response.status_code == 200
    statement, params = db.statements[1]
    assert "fixture-role" not in str(statement) and "other-role" not in str(statement)
    assert params["agent_roles"] == ["fixture-role", "other-role"]
    assert "ORDER BY a.slug" in str(statement)
    assert "ORDER BY ap.priority, ap.prompt_id" in str(statement)


@pytest.mark.parametrize("roles", [[], ["a' OR true --"], [""], ["/fixture"], ["x" * 51]])
async def test_agent_export_requires_valid_role_slugs(client: AsyncClient, db: _Session, roles: list[str]) -> None:
    response = await client.get("/api/context-export/agents", params=[("agent_role", role) for role in roles], headers=HEADERS)
    assert response.status_code == 422
    assert db.statements == []


async def test_agent_roles_are_not_silently_ignored_for_other_collections(client: AsyncClient, db: _Session) -> None:
    response = await client.get("/api/context-export/memories", params={"agent_role": "fixture-role"}, headers=HEADERS)
    assert response.status_code == 422
    assert db.statements == []


async def test_database_errors_do_not_include_row_values(client: AsyncClient, db: _Session, caplog: pytest.LogCaptureFixture) -> None:
    db.failure = SQLAlchemyError("fixture-private-row-content")
    response = await client.get("/api/context-export/memories", headers=HEADERS)
    assert response.status_code == 503
    assert response.json() == {"detail": "Context export is unavailable."}
    assert "fixture-private-row-content" not in response.text + caplog.text
