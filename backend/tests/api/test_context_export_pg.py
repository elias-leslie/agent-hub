"""Execute exports only against temporary fixture tables in the test database."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.context_export import router
from app.db import get_db

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def fixture_client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient]:
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            # No public-table fallback: every row the route can read is a fixture.
            await connection.execute(text("SET search_path TO pg_temp"))
            await connection.execute(text("""CREATE TEMP TABLE project_permissions (
                id integer, project_id text, root_path text, updated_at text, created_at text,
                daily_cost_budget_usd double precision, monthly_cost_budget_usd double precision,
                budget_alert_threshold double precision)"""))
            await connection.execute(text("""INSERT INTO project_permissions VALUES
                (9, 'fixture-z', '/fixture/é', 'updated-z', 'created-z', NULL, 2.5, 0.8),
                (2, 'fixture-a', '/fixture/a', 'updated-a', 'created-a', 1, NULL, 0.8)"""))
            await connection.execute(text("""CREATE TEMP TABLE agents (
                id integer, slug text, name text, description text, updated_at text)"""))
            await connection.execute(text("""INSERT INTO agents VALUES
                (1, 'fixture-b', 'B', NULL, 'updated'), (2, 'fixture-a', 'A', 'fixture', 'updated'),
                (3, 'unselected-fixture', 'Unselected', NULL, 'updated')"""))
            await connection.execute(text("""CREATE TEMP TABLE prompts (
                id integer, enabled boolean, slug text DEFAULT 'fixture', name text DEFAULT 'Fixture',
                description text, content text DEFAULT 'fixture content', prompt_type text DEFAULT 'system',
                is_global boolean DEFAULT true, boot_eligible boolean DEFAULT false,
                context_policy jsonb, updated_at text DEFAULT 'updated')"""))
            await connection.execute(text("INSERT INTO prompts (id, enabled) VALUES (1, true), (2, true), (3, false), (4, true)"))
            await connection.execute(text("CREATE TEMP TABLE agent_prompts (agent_id integer, prompt_id integer, priority integer)"))
            await connection.execute(text("INSERT INTO agent_prompts VALUES (2, 2, 5), (2, 4, 1), (2, 1, 5), (2, 3, 0)"))
            await connection.execute(text("""CREATE TEMP TABLE memories (
                id text, status text, group_id text, scope text DEFAULT 'global', scope_id text,
                summary text, content text DEFAULT 'fixture memory', tags text[], tier integer DEFAULT 2,
                pinned boolean, render_mode text, trigger_task_types text[], applicability jsonb,
                loaded_count integer, helpful_count integer, harmful_count integer, version integer,
                created_at text DEFAULT 'created', updated_at text DEFAULT 'updated')"""))
            await connection.execute(text("INSERT INTO memories (id, status) VALUES ('fixture-z', 'active'), ('fixture-archived', 'archived'), ('fixture-a', 'active')"))
            await connection.execute(text("""CREATE TEMP TABLE memory_settings (
                id integer, enabled boolean, total_budget integer, budget_enabled boolean,
                max_mandates integer, max_guardrails integer, reference_index_enabled boolean,
                continuity_enabled boolean, continuity_max_sessions integer, active_variant text)"""))
            await connection.execute(text("INSERT INTO memory_settings (id, enabled, total_budget) VALUES (9, false, 90), (2, true, 20)"))
            await connection.execute(text("""CREATE TEMP TABLE context_budgets (
                harness text, role text, warn_tokens integer, jump_pct integer, note text, updated_at text)"""))
            await connection.execute(text("""INSERT INTO context_budgets VALUES
                ('codex', 'review', 30, NULL, NULL, 'updated'),
                ('claude', 'review', 20, 25, 'fixture', 'updated'),
                ('claude', 'implementation', 10, NULL, NULL, 'updated')"""))
            await connection.commit()
            monkeypatch.setattr("app.middleware.access_control_auth.get_cached_client", AsyncMock(return_value={"status": "active"}))
            app = FastAPI()
            app.include_router(router, prefix="/api")

            async def fixture_db() -> AsyncGenerator[AsyncSession]:
                async with AsyncSession(bind=connection) as session:
                    try:
                        yield session
                    finally:
                        assert (await session.execute(text("SHOW transaction_read_only"))).scalar_one() == "on"
                        await session.rollback()

            app.dependency_overrides[get_db] = fixture_db
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={
                "X-Agent-Hub-Internal": "agent-hub-internal-v1", "X-Client-Id": "fixture-service",
            }) as http:
                yield http
    finally:
        await engine.dispose()


async def test_project_pages_preserve_row_to_json_column_order_and_newline_hash(fixture_client: AsyncClient) -> None:
    first = await fixture_client.get("/api/context-export/project_rows", params={"limit": 1})
    second = await fixture_client.get("/api/context-export/project_rows", params={"limit": 1, "offset": first.json()["next_offset"]})
    assert first.status_code == second.status_code == 200
    assert first.json()["next_offset"] == 1 and second.json()["next_offset"] is None
    rows = first.json()["rows"] + second.json()["rows"]
    assert [json.loads(row)["id"] for row in rows] == [2, 9]
    assert all(list(json.loads(row)) == [
        "id", "project_id", "root_path", "updated_at", "created_at", "daily_cost_budget_usd",
        "monthly_cost_budget_usd", "budget_alert_threshold",
    ] for row in rows)
    digest = hashlib.sha256("\n".join(rows).encode()).hexdigest()
    hashed = await fixture_client.get("/api/context-export/project_hash")
    assert hashed.status_code == 200
    assert hashed.json() == {"rows": [json.dumps(digest)], "next_offset": None}
    beyond = await fixture_client.get("/api/context-export/project_hash", params={"offset": 1})
    assert beyond.json() == {"rows": [], "next_offset": None}


async def test_bound_agent_roles_and_enabled_prompt_priority_order(fixture_client: AsyncClient) -> None:
    response = await fixture_client.get("/api/context-export/agents", params=[("agent_role", "fixture-b"), ("agent_role", "fixture-a")])
    assert response.status_code == 200
    assert [json.loads(row) for row in response.json()["rows"]] == [
        {"slug": "fixture-a", "name": "A", "description": "fixture", "updated_at": "updated", "prompt_ids": [4, 1, 2]},
        {"slug": "fixture-b", "name": "B", "description": None, "updated_at": "updated", "prompt_ids": None},
    ]
    assert response.json()["next_offset"] is None


async def test_context_collections_keep_the_original_fields_filters_and_order(fixture_client: AsyncClient) -> None:
    exported = {}
    for collection in ("memories", "memory_settings", "prompts", "budgets"):
        response = await fixture_client.get(f"/api/context-export/{collection}")
        assert response.status_code == 200
        exported[collection] = [json.loads(row) for row in response.json()["rows"]]
        assert response.json()["next_offset"] is None
    assert [row["id"] for row in exported["memories"]] == ["fixture-a", "fixture-z"]
    assert list(exported["memories"][0]) == [
        "id", "group_id", "scope", "scope_id", "summary", "content", "tags", "tier", "pinned",
        "render_mode", "trigger_task_types", "applicability", "loaded_count", "helpful_count",
        "harmful_count", "version", "created_at", "updated_at",
    ]
    assert [row["total_budget"] for row in exported["memory_settings"]] == [20, 90]
    assert list(exported["memory_settings"][0]) == [
        "enabled", "total_budget", "budget_enabled", "max_mandates", "max_guardrails",
        "reference_index_enabled", "continuity_enabled", "continuity_max_sessions", "active_variant",
    ]
    assert [row["id"] for row in exported["prompts"]] == [1, 2, 4]
    assert list(exported["prompts"][0]) == [
        "id", "slug", "name", "description", "content", "prompt_type", "is_global", "boot_eligible",
        "context_policy", "updated_at",
    ]
    assert [(row["harness"], row["role"]) for row in exported["budgets"]] == [
        ("claude", "implementation"), ("claude", "review"), ("codex", "review"),
    ]
    assert list(exported["budgets"][0]) == ["harness", "role", "warn_tokens", "jump_pct", "note", "updated_at"]
