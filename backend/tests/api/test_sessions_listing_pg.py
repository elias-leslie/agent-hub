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
from app.models import CostLog, Session, SessionBinding, SessionEvent, UsageCall, UsageSession
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
            for table in (Session.__table__, SessionEvent.__table__, CostLog.__table__, Agent.__table__,
                          UsageCall.__table__, UsageSession.__table__, SessionBinding.__table__):
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


async def test_detail_without_events_handles_late_turns(api: httpx.AsyncClient, pg_db: AsyncSession) -> None:
    # Regression: the agent ordering key turn * 1e9 overflowed int4 from turn 3.
    await add_session(pg_db, "long", minutes=1)
    await add_event(pg_db, "long", 1, 0, "user_message", role="user", content="start", tokens=1)
    await add_event(pg_db, "long", 40, 7, "assistant_message", role="assistant", content="late", tokens=2, agent_id="coder")

    response = await api.get("/api/sessions/long?include_events=false")
    assert response.status_code == 200, response.text
    assert [row["agent_id"] for row in response.json()["agent_token_breakdown"]] == ["default", "coder"]


async def test_title_skips_harness_scaffolding(api: httpx.AsyncClient, pg_db: AsyncSession) -> None:
    await add_session(pg_db, "codex", minutes=1)
    await add_event(pg_db, "codex", 1, 0, "user_message", role="user", content="# AGENTS.md instructions for /srv/x\n...")
    await add_event(pg_db, "codex", 1, 1, "user_message", role="user", content="  <environment_context>\n<cwd>/srv</cwd>")
    await add_event(pg_db, "codex", 1, 2, "user_message", role="user", content="<task-notification>done</task-notification>")
    await add_event(pg_db, "codex", 1, 3, "user_message", role="user", content='<pasted_content id="p1">brief</pasted_content>')
    await add_event(pg_db, "codex", 1, 4, "user_message", role="user", content="Message Type: NEW_TASK\nDo it")
    await add_event(pg_db, "codex", 1, 5, "user_message", role="user", content="The following is the Codex agent history so far")
    await add_event(pg_db, "codex", 2, 0, "user_message", role="user", content="Ship the <b>bold</b> fix")
    await add_session(pg_db, "only-scaffold", minutes=0)
    await add_event(pg_db, "only-scaffold", 1, 0, "user_message", role="user", content="<environment_context/>")

    await add_session(pg_db, "child", minutes=0)
    child = await pg_db.get(Session, "child")
    assert child is not None
    child.provider_metadata = {
        "external_identity": {"agent_path": "/root/st_context_dedup", "display_identity": "Laplace the 2nd"}
    }
    await pg_db.flush()
    await add_event(pg_db, "child", 1, 0, "user_message", role="user", content="Message Type: NEW_TASK")

    _, body = await list_ids(api)
    by_id = {item["id"]: item for item in body["sessions"]}
    assert by_id["child"]["title"] == "st_context_dedup · Laplace the 2nd"
    assert by_id["codex"]["title"] == "Ship the <b>bold</b> fix"
    assert by_id["only-scaffold"]["title"] == "<environment_context/>"


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


def _call(key: str, session_id: str, agent_id: str = "", *, minutes: int = 0, usd: float | None = 1.0) -> UsageCall:
    return UsageCall(
        call_key=key, occurred_at=BASE + timedelta(minutes=minutes), provider="codex", session_id=session_id,
        agent_id=agent_id, model="gpt-test", input_tokens=100, cached_input_tokens=40, cache_write_tokens=0,
        output_tokens=10, api_equiv_usd=usd,
    )


async def test_sessions_without_native_usage_read_the_call_ledger(api: httpx.AsyncClient, pg_db: AsyncSession) -> None:
    # A review-mode Codex parent has no token events of its own; its child thread did the work.
    await add_session(pg_db, "parent", minutes=1)
    await add_session(pg_db, "child", minutes=2, parent="parent")
    await add_session(pg_db, "completion", minutes=3, session_type="completion")
    pg_db.add_all([_call("c1", "parent", "child"), _call("c2", "parent", "child")])
    pg_db.add(CostLog(session_id="completion", model="gpt-test", input_tokens=7, output_tokens=3, cost_usd=0.0,
                      cache_read_tokens=2, cache_write_tokens=0))
    await pg_db.flush()

    _, body = await list_ids(api, "include_children=true")
    by_id = {item["id"]: item for item in body["sessions"]}
    assert (by_id["parent"]["usage_known"], by_id["parent"]["usage_input_tokens"]) == (True, 280)
    assert (by_id["child"]["usage_input_tokens"], by_id["child"]["usage_cached_input_tokens"]) == (280, 80)
    assert (by_id["completion"]["usage_input_tokens"], by_id["completion"]["usage_output_tokens"]) == (9, 3)


async def test_spend_overview_ranks_sessions_and_routine_jobs(pg_db: AsyncSession) -> None:
    from app.services import usage_costs

    now = BASE + timedelta(minutes=50)
    for sid, kind, job in (("s-int", "interactive", None), ("run-1", "routine", "neri · audit"),
                           ("run-2", "routine", "neri · audit")):
        pg_db.add(UsageSession(provider="codex", session_id=sid, agent_id="", project="neri", kind=kind, job=job,
                               title=f"title {sid}", first_at=BASE, last_at=BASE))
    pg_db.add(UsageSession(provider="codex", session_id="s-int", agent_id="sub", project="neri", kind="other",
                           title="helper", first_at=BASE, last_at=BASE))
    pg_db.add_all([
        _call("k1", "s-int", usd=5.0), _call("k2", "s-int", "sub", usd=3.0),
        _call("k3", "run-1", usd=1.0), _call("k4", "run-2", minutes=30, usd=1.0), _call("k5", "run-2", usd=None),
    ])
    await pg_db.flush()

    data = await usage_costs.overview(pg_db, "1h", now=now)
    assert [(i["key"], i["usd"], i["kind"]) for i in data["items"]] == [
        ("session:codex:s-int", 8.0, "interactive"), ("job:neri · audit", 2.0, "routine"),
    ]
    assert data["unpriced_calls"] == 1 and data["total_usd"] == 10.0
    assert sum(bar["routine"] for bar in data["chart"]) == 2.0
    assert data["summary"]["rate_per_hour"] == 0.0

    job = await usage_costs.item_detail(pg_db, "job:neri · audit", "1h", now=now)
    assert job["runs"]["count"] == 2 and job["runs"]["cost_per_run"] == 1.0
    session = await usage_costs.item_detail(pg_db, "session:codex:s-int", "1h", now=now)
    assert [(a["name"], a["usd"]) for a in session["agents"]] == [("main session", 5.0), ("helper", 3.0)]
    assert session["top_calls"][0]["usd"] == 5.0


async def test_work_role_is_fixed_across_upsert_resume_heartbeat_and_conflict(
    api: httpx.AsyncClient, pg_db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    # The isolated acceptance clone has no host ST binary; project membership
    # is outside this session-role contract.
    monkeypatch.setattr("app.constants.projects.validate_project_id", AsyncMock())
    payload = {"session_id": "fixed-role", "project_id": "agent-hub", "provider": "openai", "model": "fixture",
               "session_type": "agent", "work_role": {"id": "implementation", "source": "explicit-launch", "display_name": "Backend"},
               "provider_metadata": {"external_identity": {"display_identity": "worker"}}, "external_id": "task-fixture"}
    first = await api.post("/api/session-ingestion/sessions/upsert", json=payload)
    assert first.status_code == 200, first.text
    declaration = first.json()["session"]["work_role"]
    assert declaration["id"] == "implementation" and declaration["source"] == "explicit-launch"
    assert declaration["declared_at"]
    for declaration_input in (None, {"id": "implementation", "source": "retry", "display_name": "New name"}):
        response = await api.post("/api/session-ingestion/sessions/upsert", json={**payload, "work_role": declaration_input})
        assert response.status_code == 200, response.text
        assert response.json()["session"]["work_role"] == declaration
    heartbeat = await api.post("/api/sessions/fixed-role/heartbeat", json={"provider_metadata": {"work_role": None, "role": "review"}})
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["work_role"] == declaration
    assert heartbeat.json()["external_id"] == "task-fixture"
    assert heartbeat.json()["external_identity"]["display_identity"] == "worker"
    for path, update in (("/api/session-ingestion/sessions/upsert", {**payload, "work_role": {"id": "review", "source": "resume"}}),
                         ("/api/sessions", {**payload, "work_role": {"id": "review", "source": "resume"}}),
                         ("/api/sessions/fixed-role/heartbeat", {"provider_metadata": {"work_role": {"id": "review", "source": "resume"}}})):
        conflict = await api.post(path, json=update)
        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["error"] == "session_work_role_immutable"
    nested = {key: value for key, value in payload.items() if key != "work_role"}
    nested["session_id"] = "nested-role"
    nested["provider_metadata"] = {"work_role": payload["work_role"], "cwd": "/fixture"}
    response = await api.post("/api/session-ingestion/sessions/upsert", json=nested)
    assert response.status_code == 200, response.text
    assert response.json()["session"]["work_role"]["id"] == "implementation"
    assert response.json()["session"]["work_role"]["source"] == "explicit-launch"
    assert response.json()["session"]["work_role"]["declared_at"]
    await pg_db.rollback()  # conflict paths leave the transaction open, without writes


async def test_admin_sort_precedes_pagination_and_pins_the_window(
    api: httpx.AsyncClient, pg_db: AsyncSession,
) -> None:
    from app.services.session_ingestion._service_helpers import _merge_metadata

    metadata = _merge_metadata({}, {"work_role": {"id": "implementation", "source": "fixture"}, "harness": "codex"})
    for index, sid in enumerate(("big", "small", "missing", "empty", "excluded")):
        await add_session(pg_db, sid, minutes=index, metadata=metadata, project_id="other" if sid == "excluded" else "agent-hub")
    for sid, durations in (("big", [("Bash", 100_000, 110, 4000), ("apply_patch", 900_000, 1010, 40)]),
                           ("small", [("Bash", 20_000, 25, 100)]), ("excluded", [("Bash", 999_000, 1100, 9999)]),
                           ("missing", [("unsupported", None, 30, None)])):
        for index, (tool, duration, second, output) in enumerate(durations):
            await add_event(pg_db, sid, 1, index * 2, "tool_use", call_id=f"{sid}-{index}", tool_name=tool,
                            tool_input={"command": "st context fixture"} if tool == "Bash" else {},
                            duration_ms=duration, source_timestamp=BASE + timedelta(seconds=second))
            if output is not None:
                await add_event(pg_db, sid, 1, index * 2 + 1, "tool_result", call_id=f"{sid}-{index}",
                                tool_output={"output": "x" * output}, duration_ms=duration,
                                source_timestamp=BASE + timedelta(seconds=second))
    params = {"accounting_start": BASE.isoformat(), "accounting_end": (BASE + timedelta(hours=1)).isoformat(),
              "project_id": "agent-hub", "work_role": "implementation", "harness": "codex_cli", "page_size": 1, "sort_direction": "desc"}
    shares = await api.get("/api/sessions", params={**params, "sort_by": "admin_share"})
    assert shares.status_code == 200, shares.text
    body = shares.json()
    assert body["total"] == 4 and body["sessions"][0]["id"] == "small"
    assert body["sessions"][0]["activity_accounting"]["context_split"]["admin_share"] == 1
    next_params = {key: value for key, value in params.items() if key not in {"accounting_start", "accounting_end"}}
    second = await api.get("/api/sessions", params={**next_params, "sort_by": "admin_share", "cursor": body["next_cursor"]})
    assert second.status_code == 200, second.text
    assert second.json()["sessions"][0]["id"] == "big"
    assert second.json()["accounting_window"] == body["accounting_window"]
    accounting = second.json()["sessions"][0]["activity_accounting"]
    assert accounting["admin_share"] == 0.1  # time differs from the displayed context share
    assert accounting["context_split"]["admin_share"] > 0.98
    changed = await api.get("/api/sessions", params={**params, "sort_by": "admin_share", "cursor": body["next_cursor"],
                                                    "accounting_start": (BASE - timedelta(seconds=1)).isoformat()})
    assert changed.status_code == 422
    for field in ("admin_duration", "admin_tokens"):
        response = await api.get("/api/sessions", params={**params, "sort_by": field})
        assert response.status_code == 200, response.text
        assert response.json()["sessions"][0]["id"] == "big"
    ascending = await api.get("/api/sessions", params={**params, "sort_by": "admin_share", "sort_direction": "asc", "page_size": 100})
    assert ascending.status_code == 200, ascending.text
    rows = ascending.json()["sessions"]
    assert [row["id"] for row in rows] == ["missing", "big", "small", "empty"]
    assert rows[0]["activity_accounting"]["context_split"]["unknown_share"] == 1
    assert rows[0]["activity_accounting"]["context_split"]["tools_missing_output"] == 1
    assert rows[-1]["activity_accounting"]["context_split"]["admin_share"] is None
    assert "unknown" in {role["id"] for role in body["work_roles"]}


async def test_activity_groups_and_sessions_use_same_filters_interval_and_ledger(
    api: httpx.AsyncClient, pg_db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.session_ingestion._service_helpers import _merge_metadata

    for sid, project, role, harness, seconds in (("codex", "agent-hub", "implementation", "codex", 10),
                                                ("pi", "agent-hub", "research", "pi", 30),
                                                ("elsewhere", "summitflow", "implementation", "codex", 99)):
        await add_session(pg_db, sid, minutes=1, session_type="pi" if harness == "pi" else "agent",
                          metadata=_merge_metadata({}, {"work_role": {"id": role, "source": "fixture"}, "harness": harness}))
        await add_event(pg_db, sid, 1, 1, "tool_use", call_id=sid, duration_ms=None if sid == "pi" else seconds * 1000,
                        tool_name="Bash", tool_input={"command": "st context fixture"}, source_timestamp=BASE + timedelta(seconds=150))
        if sid == "pi":
            await add_event(pg_db, sid, 1, 2, "tool_result", call_id=sid,
                            source_timestamp=BASE + timedelta(seconds=150 + seconds))
        session = await pg_db.get(Session, sid)
        assert session is not None
        session.project_id = project
        pg_db.add(CostLog(session_id=sid, model="fixture", input_tokens=100, output_tokens=20,
                          cache_read_tokens=50, cache_write_tokens=0, api_equiv_usd=0.03, cost_usd=0,
                          created_at=BASE + timedelta(seconds=200)))
    await pg_db.flush()
    params = {"accounting_start": BASE.isoformat(), "accounting_end": (BASE + timedelta(hours=1)).isoformat(),
              "project_id": "agent-hub", "work_role": "implementation", "harness": "codex_cli", "kind": "coding", "status": "completed"}
    activity = await api.get("/api/admin/session-efficiency", params=params)
    assert activity.status_code == 200, activity.text
    rows = await api.get("/api/sessions", params=params)
    assert rows.status_code == 200, rows.text
    chart = activity.json()
    assert chart["window_start"] == BASE.isoformat() and chart["window_end"] == (BASE + timedelta(hours=1)).isoformat()
    assert rows.json()["total"] == chart["sessions"] == 1
    accounting = rows.json()["sessions"][0]["activity_accounting"]
    assert chart["duration_split"] == {key: value for key, value in accounting.items() if key != "context_split"}
    assert chart["context_split"] == accounting["context_split"]
    assert chart["by_project"][0]["context_split"] == chart["context_split"]
    assert chart["duration_split"]["admin_seconds"] == 10
    assert chart["by_project"][0]["project_id"] == "agent-hub"
    assert chart["by_work_role"][0]["work_role_id"] == "implementation"
    assert chart["by_harness"][0]["harness_id"] == "codex_cli"
    assert chart["by_harness"][0]["usage"]["input_tokens"] == 150
    assert chart["by_harness"][0]["cost"]["cash_usd"] == 0
    assert chart["by_harness"][0]["cost"]["api_equiv_usd"] == 0.03
    # Capping Activity's sample must not cap the full-session sort ledger.
    monkeypatch.setattr("app.services.admin_activity_cost.EVENT_LIMIT", 1)
    capped = await api.get("/api/admin/session-efficiency", params={key: value for key, value in params.items() if key not in {"work_role", "harness"}})
    assert capped.status_code == 200, capped.text
    assert capped.json()["events_truncated"]
    assert all(row["duration_split"]["events_truncated"] for row in capped.json()["by_project"])
    assert {row["harness_id"] for row in capped.json()["by_harness"]} == {"codex_cli", "pi"}
    complete = await api.get("/api/sessions", params={**params, "work_role": "research", "harness": "pi", "sort_by": "admin_duration"})
    assert complete.status_code == 200, complete.text
    assert complete.json()["sessions"][0]["activity_accounting"]["admin_seconds"] == 30
    assert complete.json()["sessions"][0]["activity_accounting"]["events_truncated"] is False


async def test_context_counts_retained_summary_without_claiming_full_output(
    api: httpx.AsyncClient, pg_db: AsyncSession,
) -> None:
    await add_session(pg_db, "summary", minutes=1)
    await add_event(pg_db, "summary", 1, 1, "tool_use", call_id="summary",
                    tool_name="Bash", tool_input={"command": "st context fixture"})
    await add_event(pg_db, "summary", 1, 2, "tool_result", call_id="summary",
                    content="x" * 2000, tool_output={"result": {"unretained": True}})
    response = await api.get("/api/sessions", params={
        "accounting_start": BASE.isoformat(), "accounting_end": (BASE + timedelta(hours=1)).isoformat(),
    })
    assert response.status_code == 200, response.text
    context = response.json()["sessions"][0]["activity_accounting"]["context_split"]
    # Coverage means retained text exists; this summary is not the full output.
    assert context["tools_sampled"] == 1 and context["tools_missing_output"] == 0
    assert context["returned_tokens_estimate"] == 500


@pytest.mark.parametrize("retained,expected", [("", 0), ("private-fixture" * 40, 150)])
async def test_pi_tool_result_text_counts_without_returning_its_body(
    api: httpx.AsyncClient, pg_db: AsyncSession, retained: str, expected: int,
) -> None:
    await add_session(pg_db, "pi-text", minutes=1, session_type="pi")
    await add_event(pg_db, "pi-text", 1, 1, "tool_use", call_id="call",
                    tool_name="bash", tool_input={"command": "st context fixture"})
    await add_event(pg_db, "pi-text", 1, 2, "tool_result", call_id="call",
                    tool_output={"text": retained, "isError": False})
    params = {"accounting_start": BASE.isoformat(), "accounting_end": (BASE + timedelta(hours=1)).isoformat()}
    response = await api.get("/api/sessions", params=params)
    assert response.status_code == 200, response.text
    context = response.json()["sessions"][0]["activity_accounting"]["context_split"]
    assert context["tools_sampled"] == 1 and context["tools_missing_output"] == 0
    assert context["returned_tokens_estimate"] == expected
    activity = await api.get("/api/admin/session-efficiency", params=params)
    assert activity.status_code == 200, activity.text
    assert activity.json()["context_split"] == context
    assert "private-fixture" not in response.text + activity.text


async def test_detail_carries_the_session_cost_tool_places_and_thinking_time(
    api: httpx.AsyncClient, pg_db: AsyncSession
) -> None:
    await add_session(pg_db, "chat", minutes=1, session_type="completion")
    await add_session(pg_db, "free", minutes=2, session_type="completion")
    await add_event(pg_db, "chat", 1, 1, "user_message", role="user", content="fix")
    await add_event(pg_db, "chat", 1, 2, "thinking", content="plan", duration_ms=2500)
    await add_event(pg_db, "chat", 1, 3, "tool_use", tool_name="read", call_id="c1", content_offset=11)
    await add_event(pg_db, "chat", 1, 4, "assistant_message", role="assistant", content="Looking... Fixed.")
    pg_db.add_all([
        CostLog(session_id="chat", model="m", input_tokens=10, output_tokens=5, cost_usd=0.004),
        CostLog(session_id="chat", model="m", input_tokens=10, output_tokens=5, cost_usd=0.006),
        # A subscription call costs $0 cash; its list-price value is not spend, and a live turn does not show it.
        CostLog(session_id="chat", model="m", input_tokens=10, output_tokens=5, cost_usd=0.0, api_equiv_usd=0.5),
    ])
    await pg_db.flush()

    chat = (await api.get("/api/sessions/chat")).json()
    answer = chat["messages"][1]
    assert chat["total_cost_usd"] == pytest.approx(0.01)
    assert [(t["name"], t["content_offset"]) for t in answer["tool_executions"]] == [("read", 11)]
    assert answer["thinking_ms"] == 2500
    # Nothing logged is unknown, not free.
    assert (await api.get("/api/sessions/free")).json()["total_cost_usd"] is None
    events = (await api.get("/api/sessions/chat/events")).json()["events"]
    assert [e["content_offset"] for e in events if e["event_type"] == "tool_use"] == [11]


async def _hub_turn(db: AsyncSession, session_id: str, model: str, **named: str) -> Session:
    """One Agent Hub turn on agent `coder` (whose own model is codex/gpt-6.1-sol), as the request path opens it."""
    from app.api.complete.session_repo import get_or_create_session

    session, _, _ = await get_or_create_session(
        db, session_id, "agent-hub", model.split("/")[0], model, session_type="chat", agent_slug="coder", **named
    )
    await db.commit()
    return session


@pytest.fixture
def agent_default_codex(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    monkeypatch.setattr("app.constants.projects.validate_project_id", AsyncMock())
    resolved = SimpleNamespace(provider="codex", model="codex/gpt-6.1-sol")
    monkeypatch.setattr("app.services.session_ingestion.service.resolve_agent", AsyncMock(return_value=resolved))


def _route(session: Session) -> tuple[str, str, bool]:
    from app.services._session_metadata_helpers import session_model_info

    info = session_model_info(session)
    return str(info["requested_model"]), str(info["effective_model"]), bool(info["fallback_used"])


async def test_turn_override_that_answers_is_not_a_fallback(pg_db: AsyncSession, agent_default_codex: None) -> None:
    # The model picker names deepseek for a turn on an agent whose default is codex: that turn asked for deepseek.
    session = await _hub_turn(pg_db, "override-served", "opencode-go/deepseek-v4.1-flash")
    assert _route(session) == ("opencode-go/deepseek-v4.1-flash", "opencode-go/deepseek-v4.1-flash", False)
    assert session.model == "opencode-go/deepseek-v4.1-flash"
    assert session.models_used == ["opencode-go/deepseek-v4.1-flash"]
    # The next message in the same session, with the same pick, stays the same.
    again = await _hub_turn(pg_db, "override-served", "opencode-go/deepseek-v4.1-flash")
    assert _route(again) == ("opencode-go/deepseek-v4.1-flash", "opencode-go/deepseek-v4.1-flash", False)


async def test_turn_override_answered_by_another_model_is_a_fallback(pg_db: AsyncSession, agent_default_codex: None) -> None:
    await _hub_turn(pg_db, "override-fell-back", "opencode-go/deepseek-v4.1-flash")
    # The turn named deepseek, the route failed over to another model and answered there.
    session = await _hub_turn(
        pg_db, "override-fell-back", "zai/glm-5.1", requested_provider="opencode-go", requested_model="opencode-go/deepseek-v4.1-flash"
    )
    assert _route(session) == ("opencode-go/deepseek-v4.1-flash", "zai/glm-5.1", True)


async def test_turn_without_override_keeps_the_agent_default(pg_db: AsyncSession, agent_default_codex: None) -> None:
    session = await _hub_turn(pg_db, "agent-default", "codex/gpt-6.1-sol")
    assert _route(session) == ("codex/gpt-6.1-sol", "codex/gpt-6.1-sol", False)
    # A later turn that does name a model is its own choice, not the session's earlier default.
    later = await _hub_turn(pg_db, "agent-default", "opencode-go/deepseek-v4.1-flash")
    assert _route(later) == ("opencode-go/deepseek-v4.1-flash", "opencode-go/deepseek-v4.1-flash", False)
