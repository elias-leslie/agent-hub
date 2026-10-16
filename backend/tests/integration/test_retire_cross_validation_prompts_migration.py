"""Verify the cross-validation prompt retirement on disposable PostgreSQL tables, including rollback."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db import _get_engine

_PATH = Path(__file__).resolve().parents[2] / "alembic/versions/c5e8a2d4f1b7_retire_portfolio_cross_validation_prompts.py"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cross_validation_prompt_retirement_checks_preimage_and_rolls_back() -> None:
    async with _get_engine().connect() as connection:
        assert (await connection.execute(sa.text("SELECT current_database()"))).scalar() == "agent_hub_test"
        try:
            await connection.run_sync(_verify_migration)
        finally:
            await connection.rollback()


def _load():
    spec = importlib.util.spec_from_file_location(_PATH.stem, _PATH)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _prompts(conn) -> dict[str, dict]:
    rows = conn.execute(sa.text("SELECT row_to_json(p) AS r FROM prompts p")).scalars()
    return {row["slug"]: row for row in rows}


def _links(conn) -> dict[str, int | None]:
    rows = conn.execute(sa.text("SELECT CAST(id AS text), prompt_id FROM prompt_revisions")).all()
    return dict(rows)


def _verify_migration(conn) -> None:
    migration = _load()
    data = migration._data()
    recorded = {row["slug"]: row for row in data["prompts"]}
    assert set(recorded) == {
        "portfolio-cross-validation-review-system",
        "portfolio-cross-validation-review-template",
    }
    # pg_temp shadows the public tables. No shared fixture or durable row is changed.
    conn.execute(sa.text("CREATE TEMP TABLE prompts (LIKE public.prompts INCLUDING ALL) ON COMMIT DROP"))
    conn.execute(sa.text(
        "CREATE TEMP TABLE prompt_revisions (id UUID PRIMARY KEY, "
        "prompt_id INT REFERENCES prompts(id) ON DELETE SET NULL) ON COMMIT DROP"
    ))
    conn.execute(sa.text(
        "CREATE TEMP TABLE agent_prompts (agent_id INT, "
        "prompt_id INT REFERENCES prompts(id) ON DELETE CASCADE) ON COMMIT DROP"
    ))
    keeper = {**data["prompts"][0], "id": 900001, "slug": "portfolio-keeper", "name": "Keeper"}
    conn.execute(
        sa.text("INSERT INTO prompts SELECT * FROM json_populate_recordset(NULL::prompts, CAST(:rows AS json))"),
        {"rows": json.dumps([*data["prompts"], keeper])},
    )
    conn.execute(
        sa.text("INSERT INTO prompt_revisions VALUES (CAST(:id AS uuid), :prompt_id)"),
        [*data["prompt_revision_links"], {"id": "00000000-0000-0000-0000-000000000001", "prompt_id": 900001}],
    )
    links = {link["id"]: link["prompt_id"] for link in data["prompt_revision_links"]}

    with Operations.context(MigrationContext.configure(conn)):
        # Refusals leave every row in place.
        system_id = recorded["portfolio-cross-validation-review-system"]["id"]
        conn.execute(sa.text("UPDATE prompts SET content = content || 'x' WHERE id = :id"), {"id": system_id})
        with pytest.raises(RuntimeError, match="differ from the recorded preimage"):
            migration.upgrade()
        conn.execute(sa.text("UPDATE prompts SET content = left(content, -1) WHERE id = :id"), {"id": system_id})
        conn.execute(sa.text("INSERT INTO agent_prompts VALUES (1, :id)"), {"id": system_id})
        with pytest.raises(RuntimeError, match="assigned to an agent"):
            migration.upgrade()
        conn.execute(sa.text("DELETE FROM agent_prompts"))
        extra = "00000000-0000-0000-0000-000000000002"
        conn.execute(sa.text("INSERT INTO prompt_revisions VALUES (CAST(:id AS uuid), :p)"), {"id": extra, "p": system_id})
        with pytest.raises(RuntimeError, match="gained revisions"):
            migration.upgrade()
        conn.execute(sa.text("DELETE FROM prompt_revisions WHERE id = CAST(:id AS uuid)"), {"id": extra})
        assert set(_prompts(conn)) == {*recorded, "portfolio-keeper"}

        migration.upgrade()
        assert set(_prompts(conn)) == {"portfolio-keeper"}
        assert _links(conn) == {**dict.fromkeys(links), "00000000-0000-0000-0000-000000000001": 900001}
        migration.upgrade()  # already gone: a no-op, not a refusal

        migration.downgrade()
        restored = _prompts(conn)
        for slug, row in recorded.items():
            assert {**restored[slug], "created_at": None, "updated_at": None} == {
                **row, "created_at": None, "updated_at": None,
            }
        assert _links(conn) == {**links, "00000000-0000-0000-0000-000000000001": 900001}
        with pytest.raises(RuntimeError, match="exists again"):
            migration.downgrade()
