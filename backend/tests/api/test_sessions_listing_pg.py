"""PostgreSQL contracts for the sessions list, facets, detail and events windows.

Runs against the explicit test database inside one rolled-back transaction with
private tables in a throwaway schema, so nothing persists.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import Enum, make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.db import get_db
from app.main import app
from app.models import CostLog, Session, SessionEvent
from app.models.agent import Agent
from tests.conftest import TEST_HEADERS

pytestmark = pytest.mark.integration

BASE = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def pg_db() -> AsyncGenerator[AsyncSession]:
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test"), "Session listing tests require a test database"
    engine = create_async_engine(url)
    schema = f"sessions_listing_{uuid4().hex}"
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.execute(text(f"SET LOCAL search_path TO {schema}"))

        def create_tables(sync_connection: Any) -> None:
            for table in (Session.__table__, SessionEvent.__table__, CostLog.__table__, Agent.__table__):
                for column in table.columns:
                    if isinstance(column.type, Enum):
                        column.type.create(sync_connection, checkfirst=True)
                ddl = CreateTable(table, include_foreign_key_constraints=[])
                sync_connection.execute(ddl)

        await connection.run_sync(create_tables)
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def api(pg_db: AsyncSession) -> AsyncGenerator[httpx.AsyncClient]:
    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        yield pg_db

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=TEST_HEADERS) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)


async def add_session(
    db: AsyncSession,
    session_id: str,
    *,
    minutes: int,
    session_type: str = "agent",
    status: str = "completed",
    project_id: str = "agent-hub",
    parent: str | None = None,
    metadata: dict[str, Any] | None = None,
    models_used: list[str] | None = None,
    model: str = "gpt-test",
    branch: str | None = None,
    summary: str | None = None,
    last_activity: bool = True,
) -> Session:
    created = BASE + timedelta(minutes=minutes)
    session = Session(
        id=session_id,
        project_id=project_id,
        provider="codex",
        model=model,
        status=status,
        session_type=session_type,
        parent_session_id=parent,
        provider_metadata=metadata or {},
        models_used=models_used or [],
        current_branch=branch,
        summary_oneliner=summary,
        created_at=created,
        updated_at=BASE + timedelta(days=30),  # bulk-touched; must not drive last_active
        last_activity_at=created + timedelta(seconds=30) if last_activity else None,
    )
    db.add(session)
    await db.flush()
    return session


async def add_event(
    db: AsyncSession,
    session_id: str,
    turn: int,
    sequence: int,
    event_type: str,
    **fields: Any,
) -> None:
    db.add(
        SessionEvent(
            session_id=session_id,
            turn=turn,
            sequence=sequence,
            event_type=event_type,
            created_at=BASE + timedelta(seconds=turn * 100 + sequence),
            **fields,
        )
    )
    await db.flush()


async def list_ids(api: httpx.AsyncClient, query: str = "") -> tuple[list[str], dict[str, Any]]:
    response = await api.get(f"/api/sessions?{query}")
    assert response.status_code == 200, response.text
    body = response.json()
    return [item["id"] for item in body["sessions"]], body


async def test_no_new_params_keeps_status_order_all_kinds_children_and_shape(
    api: httpx.AsyncClient, pg_db: AsyncSession
) -> None:
    await add_session(pg_db, "s-completion", minutes=1, session_type="completion")
    await add_session(pg_db, "s-active", minutes=2, status="active")
    await add_session(pg_db, "s-failed", minutes=3, status="failed", session_type="chat")
    await add_session(pg_db, "s-child", minutes=4, parent="s-active")
    await add_session(pg_db, "s-bench", minutes=5, metadata={"session_kind": "benchmark"})

    ids, body = await list_ids(api)

    # Status rank asc (active, failed, others), then activity desc: unchanged default.
    assert ids == ["s-active", "s-failed", "s-bench", "s-child", "s-completion"]
    assert body["total"] == 5
    assert body["page"] == 1 and body["page_size"] == 20
    assert body["next_cursor"] is None
    item = body["sessions"][0]
    for legacy_key in (
        "message_count", "event_count", "total_input_tokens", "total_output_tokens",
        "child_session_count", "active_child_session_count", "attribution_kind", "live_activity",
    ):
        assert legacy_key in item
    assert item["child_session_count"] == 1

    page_two, body = await list_ids(api, "page=2&page_size=2")
    assert page_two == ["s-bench", "s-child"]
    assert body["total"] == 5

    filtered, body = await list_ids(api, "parent_session_id=s-active&project_id=agent-hub&status=completed")
    assert filtered == ["s-child"]
    assert body["total"] == 1


async def test_new_filters_kind_roots_benchmarks_since_model_and_q(
    api: httpx.AsyncClient, pg_db: AsyncSession
) -> None:
    await add_session(pg_db, "aaaa-code", minutes=1, branch="task-42/main")
    await add_session(pg_db, "bbbb-cc", minutes=2, session_type="claude_code", summary="Fix 100% CPU")
    await add_session(pg_db, "cccc-chat", minutes=3, session_type="chat", model="claude-x")
    await add_session(pg_db, "dddd-comp", minutes=4, session_type="completion")
    await add_session(pg_db, "eeee-img", minutes=5, session_type="image_generation")
    await add_session(pg_db, "ffff-child", minutes=6, parent="aaaa-code")
    await add_session(pg_db, "gggg-bench", minutes=7, metadata={"session_kind": "benchmark"})
    await add_session(
        pg_db, "hhhh-req", minutes=8, metadata={"requested_model": "gpt-requested"}, model="gpt-effective"
    )
    await add_session(pg_db, "iiii-used", minutes=9, models_used=["unknown", "gpt-used", "gpt-later"], model="gpt-x")
    await add_session(pg_db, "jjjj-old", minutes=-600, last_activity=False)

    sort = "sort_by=last_active&sort_direction=desc"
    ids, body = await list_ids(api, f"{sort}&kind=coding,chat&roots_only=true&exclude_benchmarks=true")
    assert ids == ["iiii-used", "hhhh-req", "cccc-chat", "bbbb-cc", "aaaa-code", "jjjj-old"]
    assert body["total"] == 6

    ids, _ = await list_ids(api, f"{sort}&kind=completion,image")
    assert ids == ["eeee-img", "dddd-comp"]
    assert (await api.get("/api/sessions?kind=bogus")).status_code == 422

    since = (BASE + timedelta(minutes=7)).isoformat()
    ids, _ = await list_ids(api, f"{sort}&since={since.replace('+', '%2B')}")
    assert ids == ["iiii-used", "hhhh-req", "gggg-bench"]

    ids, _ = await list_ids(api, "model=gpt-requested")
    assert ids == ["hhhh-req"]
    ids, _ = await list_ids(api, "model=gpt-used")
    assert ids == ["iiii-used"]
    ids, _ = await list_ids(api, "model=gpt-effective")
    assert ids == []

    ids, _ = await list_ids(api, "q=AAAA")
    assert ids == ["aaaa-code"]
    ids, _ = await list_ids(api, "q=task-42")
    assert ids == ["aaaa-code"]
    ids, _ = await list_ids(api, "q=100%25")
    assert ids == ["bbbb-cc"]
    ids, _ = await list_ids(api, "q=claude-x")
    assert ids == ["cccc-chat"]
    ids, _ = await list_ids(api, "q=code")  # id prefix only: "aaaa-code" does not start with "code"
    assert ids == []


async def _walk(api: httpx.AsyncClient, query: str, on_page: Any = None) -> list[str]:
    seen: list[str] = []
    cursor: str | None = None
    for page_index in range(20):
        suffix = f"&cursor={cursor}" if cursor else ""
        ids, body = await list_ids(api, f"{query}&page_size=2{suffix}")
        seen.extend(ids)
        cursor = body["next_cursor"]
        if on_page is not None:
            await on_page(page_index)
        if cursor is None:
            return seen
    raise AssertionError("cursor walk did not terminate")


@pytest.mark.parametrize(
    "query",
    ["sort_by=last_active&sort_direction=desc", "sort_by=status&sort_direction=asc"],
)
async def test_keyset_cursor_has_no_duplicates_or_skips_under_inserts(
    api: httpx.AsyncClient, pg_db: AsyncSession, query: str
) -> None:
    original = []
    for index in range(7):
        session_id = f"k-{index}"
        # Equal timestamps for pairs exercise the id tie-break.
        await add_session(pg_db, session_id, minutes=index // 2, status="failed" if index == 3 else "completed")
        original.append(session_id)

    async def insert_newer(page_index: int) -> None:
        await add_session(pg_db, f"new-{page_index}", minutes=1000 + page_index, status="active")

    seen = await _walk(api, query, insert_newer)

    assert len(seen) == len(set(seen))
    assert set(original) <= set(seen)
    assert not (set(seen) - set(original) - {f"new-{i}" for i in range(20)})

    _, first_page = await list_ids(api, f"{query}&page_size=1")
    mismatched = await api.get(f"/api/sessions?sort_by=time&cursor={first_page['next_cursor']}")
    assert mismatched.status_code == 422
    assert (await api.get("/api/sessions?cursor=not-a-cursor")).status_code == 422


async def test_live_status_aliases_count_before_paging(api: httpx.AsyncClient, pg_db: AsyncSession) -> None:
    await add_session(pg_db, "stale-1", minutes=1, status="active", metadata={"live_activity": {"is_stale": True}})
    await add_session(pg_db, "stale-2", minutes=2, status="active", metadata={"live_activity": {"status": "Stalled"}})
    await add_session(
        pg_db, "reap-1", minutes=3, status="active", metadata={"live_activity": {"reapable": True}}
    )
    await add_session(pg_db, "live-1", minutes=4, status="active", metadata={"live_activity": {"status": "active"}})
    await add_session(pg_db, "done-stale", minutes=5, metadata={"live_activity": {"is_stale": True}})

    ids, body = await list_ids(api, "status=stale&page_size=1")
    assert body["total"] == 3
    assert len(ids) == 1 and body["next_cursor"] is not None

    _, body = await list_ids(api, "status=reapable")
    assert body["total"] == 1
    _, body = await list_ids(api, "status=running")
    assert body["total"] == 4  # unchanged alias: stored status active


async def test_facets_ignore_their_own_dimension(api: httpx.AsyncClient, pg_db: AsyncSession) -> None:
    await add_session(pg_db, "f-1", minutes=1, status="active", project_id="alpha")
    await add_session(pg_db, "f-2", minutes=2, status="failed", project_id="alpha", session_type="chat")
    await add_session(pg_db, "f-3", minutes=3, project_id="beta", session_type="completion")
    await add_session(pg_db, "f-4", minutes=4, project_id="beta", session_type="image_generation")
    await add_session(pg_db, "f-5", minutes=5, project_id="beta", parent="f-1")

    response = await api.get("/api/sessions/facets?status=completed&kind=coding&project_id=beta&roots_only=true")
    assert response.status_code == 200, response.text
    facets = response.json()

    # status ignores status=completed: coding + beta + roots → none (f-5 is a child).
    assert facets["status"] == {"active": 0, "completed": 0, "failed": 0, "running": 0}
    # kind ignores kind=coding: completed + beta + roots.
    assert facets["kind"] == {"coding": 0, "chat": 0, "completion": 1, "image": 1}
    # projects ignore project_id=beta: completed + coding + roots → none.
    assert facets["projects"] == []

    facets = (await api.get("/api/sessions/facets")).json()
    assert facets["status"] == {"active": 1, "completed": 3, "failed": 1, "running": 1}
    assert facets["kind"] == {"coding": 2, "chat": 1, "completion": 1, "image": 1}
    assert facets["projects"] == [{"project_id": "beta", "count": 3}, {"project_id": "alpha", "count": 2}]


async def _seed_conversation(db: AsyncSession, session_id: str) -> None:
    await add_session(db, session_id, minutes=1, status="active")
    await add_event(db, session_id, 1, 0, "user_message", role="user", content="  Fix   the\n\tlist " + "x" * 300, tokens=10)
    await add_event(db, session_id, 1, 1, "assistant_message", role="assistant", content="ok", tokens=20, agent_id="coder", agent_name="Coder")
    await add_event(db, session_id, 1, 2, "tool_use", tool_name="Bash", content="ls -la", agent_id="coder")
    await add_event(db, session_id, 1, 3, "usage", usage={"scope": "response", "source": "codex", "response_id": "r1", "input_tokens": 100, "output_tokens": 7, "cached_input_tokens": 50})
    # Same response re-ingested: deduplicated by response_id.
    await add_event(db, session_id, 1, 4, "usage", usage={"scope": "response", "source": "codex", "response_id": "r1", "input_tokens": 100, "output_tokens": 7})
    await add_event(db, session_id, 2, 0, "user_message", role="user", content="second", tokens=5)
    await add_event(db, session_id, 2, 1, "usage", usage={"scope": "response", "source": "codex", "response_id": "r2", "input_tokens": 30, "output_tokens": 3})
    # Cumulative counters and source-less records never count.
    await add_event(db, session_id, 2, 2, "usage_counter", usage={"scope": "turn", "source": "codex", "input_tokens": 999})
    await add_event(db, session_id, 2, 3, "usage", usage={"scope": "response", "input_tokens": 999})
    await add_event(db, session_id, 2, 4, "child_session_update", content="child progress")
    await add_event(db, session_id, 2, 5, "assistant_message", role="assistant", content="done", tokens=4)


async def test_list_items_carry_title_usage_and_last_active(api: httpx.AsyncClient, pg_db: AsyncSession) -> None:
    await _seed_conversation(pg_db, "conv")
    await add_session(pg_db, "silent", minutes=0, last_activity=False)

    _, body = await list_ids(api, "sort_by=last_active&sort_direction=desc")
    by_id = {item["id"]: item for item in body["sessions"]}
    conv, silent = by_id["conv"], by_id["silent"]
    assert conv["title"] == ("Fix the list " + "x" * 300)[:160]
    assert len(conv["title"]) == 160
    assert conv["usage_known"] is True
    assert (conv["usage_input_tokens"], conv["usage_output_tokens"], conv["usage_cached_input_tokens"]) == (130, 10, 50)
    assert conv["last_active_at"].startswith("2026-10-01T12:01:30")
    assert silent["title"] is None
    assert silent["usage_known"] is False
    assert silent["usage_input_tokens"] is None
    assert silent["last_active_at"].startswith("2026-10-01T12:00:00")


async def test_detail_without_events_matches_default_counts(api: httpx.AsyncClient, pg_db: AsyncSession) -> None:
    await _seed_conversation(pg_db, "conv")

    full = (await api.get("/api/sessions/conv")).json()
    lean_response = await api.get("/api/sessions/conv?include_events=false")
    assert lean_response.status_code == 200, lean_response.text
    lean = lean_response.json()

    assert full["messages"] and lean["messages"] == []
    for key in (
        "message_count", "event_count", "agent_token_breakdown", "total_input_tokens",
        "total_output_tokens", "title", "usage_known", "usage_input_tokens", "usage_output_tokens",
        "usage_cached_input_tokens", "last_active_at", "child_session_count",
    ):
        assert lean[key] == full[key], key
    assert full["message_count"] == 4
    assert full["event_count"] == 11
    assert {row["agent_id"] for row in full["agent_token_breakdown"]} == {"default", "coder"}
    assert (await api.get("/api/sessions/missing?include_events=false")).status_code == 404


async def test_events_window_filters_search_and_keyset_both_orders(
    api: httpx.AsyncClient, pg_db: AsyncSession
) -> None:
    await _seed_conversation(pg_db, "conv")
    exclude = "exclude_types=child_session_update,usage_counter"

    first = (await api.get(f"/api/sessions/conv/events?{exclude}&page_size=4")).json()
    assert first["total"] == 9
    assert [(e["turn"], e["sequence"]) for e in first["events"]] == [(1, 0), (1, 1), (1, 2), (1, 3)]
    assert first["next_after"]

    collected = list(first["events"])
    after = first["next_after"]
    while after:
        page = (
            await api.get(f"/api/sessions/conv/events?{exclude}&page_size=4&snapshot={first['snapshot']}&after={after}")
        ).json()
        collected.extend(page["events"])
        after = page["next_after"]
    assert len(collected) == 9
    assert all(e["event_type"] not in {"child_session_update", "usage_counter"} for e in collected)

    newest = (await api.get(f"/api/sessions/conv/events?order=desc&page_size=2&{exclude}")).json()
    assert [(e["turn"], e["sequence"]) for e in newest["events"]] == [(2, 5), (2, 3)]
    older = (
        await api.get(f"/api/sessions/conv/events?order=desc&page_size=2&{exclude}&after={newest['next_after']}")
    ).json()
    assert [(e["turn"], e["sequence"]) for e in older["events"]] == [(2, 1), (2, 0)]
    mixed = await api.get(f"/api/sessions/conv/events?order=asc&after={newest['next_after']}")
    assert mixed.status_code == 422
    assert (await api.get("/api/sessions/conv/events?order=sideways")).status_code == 422

    searched = (await api.get("/api/sessions/conv/events?q=BASH")).json()
    assert searched["total"] == 1 and searched["events"][0]["tool_name"] == "Bash"
    searched = (await api.get("/api/sessions/conv/events?q=second")).json()
    assert searched["total"] == 1

    legacy = (await api.get("/api/sessions/conv/events?page=3&page_size=5")).json()
    assert legacy["total"] == 11
    assert [(e["turn"], e["sequence"]) for e in legacy["events"]] == [(2, 5)]
    assert legacy["next_after"] is None
    assert legacy["max_turn"] == 2


async def test_events_summary(api: httpx.AsyncClient, pg_db: AsyncSession) -> None:
    await _seed_conversation(pg_db, "conv")
    await add_session(pg_db, "empty", minutes=2)

    summary = (await api.get("/api/sessions/conv/events/summary")).json()
    assert summary["total"] == 11
    assert summary["by_type"] == {
        "user_message": 2, "assistant_message": 2, "tool_use": 1, "usage": 4,
        "usage_counter": 1, "child_session_update": 1,
    }
    assert summary["first_user_message"].startswith("Fix the list xxx")
    assert summary["usage_known"] is True
    assert summary["usage_input_tokens"] == 130

    empty = (await api.get("/api/sessions/empty/events/summary")).json()
    assert empty == {
        "total": 0, "by_type": {}, "first_user_message": None, "usage_known": False,
        "usage_input_tokens": None, "usage_output_tokens": None, "usage_cached_input_tokens": None,
    }
    assert (await api.get("/api/sessions/missing/events/summary")).status_code == 404
