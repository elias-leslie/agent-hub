"""First-turn capture against Postgres: delivery rows bind to transcript heads and land on usage_sessions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import CreateTable

from app.models import ContextDelivery, UsageSession
from app.services.context_observability import capture, deliveries, first_turn
from tests.api.test_sessions_listing_pg import pg_db  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration

AT = datetime(2026, 11, 1, 12, tzinfo=UTC)
RENDERED = "## Safety Directive\n" + "x" * 780


def _contract(delivery_id: str, rendered: str, *, minutes: int, tags: list[str], surface: str = "claude_code") -> dict:
    return {
        "delivery_id": delivery_id, "payload_hash": deliveries.sha256_text(rendered), "status": "ok",
        "generated_at": (AT - timedelta(minutes=minutes)).isoformat(), "estimated_tokens": len(rendered) // 4, "rendered": rendered,
        "metadata": {"consumer_surface": surface, "consumer_tags": tags, "project_id": "agent-hub"},
        "blocks": [{"block_id": "b", "kind": "prompt", "estimated_tokens": 150,
                    "provenance": {"source_type": "prompt", "source_id": "p", "source_revision": "r1", "scope": "global"}},
                   {"block_id": "c", "kind": "tool_capabilities", "estimated_tokens": 45,
                    "provenance": {"source_type": "computed", "source_id": "t", "source_revision": "r2", "scope": "project"}}],
    }


@pytest_asyncio.fixture
async def db(pg_db: AsyncSession) -> AsyncSession:  # noqa: F811
    conn = await pg_db.connection()
    await conn.run_sync(lambda c: c.execute(CreateTable(ContextDelivery.__table__, include_foreign_key_constraints=[])))
    return pg_db


async def _store(db: AsyncSession, *contracts: dict, source: str = "api") -> int:
    rows = [deliveries.values_from_contract(c, source=source) for c in contracts]
    return await deliveries._insert(db, [r for r in rows if r])


async def test_a_delivery_recorded_twice_is_one_row(db: AsyncSession) -> None:
    contract = _contract("d1", RENDERED, minutes=5, tags=["work-role:hunting"])

    assert await _store(db, contract, source="api") == 1
    assert await _store(db, contract, source="file") == 0

    (row,) = (await db.execute(select(ContextDelivery))).scalars().all()
    assert (row.source, row.work_role, row.by_scope) == ("api", "hunting", {"global": 150, "project": 45})


async def test_claude_head_binds_by_the_hash_of_its_delivered_instructions(db: AsyncSession) -> None:
    await _store(db, _contract("older", RENDERED, minutes=90, tags=["work-role:review"]),
                 _contract("d1", RENDERED, minutes=5, tags=["work-role:implementation"]))
    raw = {
        "harness": "claude", "total": 9000, "first_at": AT, "model": "claude-opus-5-5", "version": "2.1.316", "fp": "shape-a",
        "sys_chars": 4000, "tools_chars": 8000, "listing_chars": 4000, "brief_chars": 400,
        "inst_files": [{"path": "/h/.local/state/agent-hub/context-deliveries/claude_code/p/s/claude-context-1/CLAUDE.md",
                        "chars": len(RENDERED), "sha": deliveries.sha256_text(RENDERED)}],
    }
    db.add(UsageSession(provider="claude", session_id="s1", agent_id="", first_at=AT, last_at=AT))
    await db.flush()

    updated = await capture.apply_first_turns(db, [capture.HeadResult("claude", "s1", "", raw, "project")])

    row = (await db.execute(select(UsageSession))).scalar_one()
    assert updated == 1 and row.parts is not None
    assert (row.delivery_id, row.work_role, row.coordinator, row.harness, row.config_fp) == ("d1", "implementation", False, "claude", "shape-a")
    assert (row.first_turn_tokens, row.launch_mode, row.harness_version) == (9000, "project", "2.1.316")
    assert row.parts["ours"] == {"tokens": len(RENDERED) // 4, "method": "estimate"}
    assert row.parts["total"]["tokens"] == 9000


async def test_codex_developer_text_binds_to_the_delivery_it_starts_with(db: AsyncSession) -> None:
    other = "## Recent Activity\n" + "y" * 500
    await _store(db, _contract("c1", RENDERED, minutes=2, tags=["aico-coordinator"], surface="codex"),
                 _contract("c2", other, minutes=1, tags=["work-role:other"], surface="codex"))

    found = await deliveries.find_delivery_in_text(db, "codex", [RENDERED + "\n<collaboration_mode>tail"], AT)

    assert found is not None
    row, chars = found
    assert (row["delivery_id"], row["work_role"], row["coordinator"], chars) == ("c1", "coordinator", True, len(RENDERED))
    assert await deliveries.find_delivery_in_text(db, "codex", ["unrelated developer text"], AT) is None


async def test_unbound_session_still_records_its_total_and_leaves_role_unknown(db: AsyncSession) -> None:
    raw = {"harness": "codex", "total": 14_000, "first_at": AT, "model": "gpt-6.1-sol", "version": "0.164.0", "fp": "f" * 16,
           "tools_chars": 4000, "base_chars": 4000, "skills_chars": 1000, "env_chars": 0, "brief_chars": 40, "dev_texts": []}
    db.add(UsageSession(provider="codex", session_id="r1", agent_id="", first_at=AT, last_at=AT))
    await db.flush()

    await capture.apply_first_turns(db, [capture.HeadResult("codex", "r1", "", raw, "project")])

    row = (await db.execute(select(UsageSession))).scalar_one()
    assert row.parts is not None
    assert (row.first_turn_tokens, row.work_role, row.delivery_id) == (14_000, None, None)
    assert row.parts["ours"]["tokens"] is None and row.parts["harness"]["tokens"] is None
    assert first_turn.est_tokens(40) == row.parts["brief"]["tokens"]
