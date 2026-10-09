"""Delete the 17 inactive agents (owner decision, 2026-10-09).

Revision ID: d1e2f3a4b5c6
Revises: c4d5e6f7a8b9

The owner chose to delete every inactive agent rather than keep them
deactivated. Deleting an agent cascades to its versions, prompt links and the
system prompt it owns. The sibling .json file holds the exact preimage of every
affected row: upgrade refuses to run unless the live rows serialize to exactly
that preimage, and downgrade restores every row with its original id.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import text

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATA_PATH = Path(__file__).with_suffix(".json")
# Restore order: parents before the rows that reference them.
_TABLES = (
    ("agents", "id"),
    ("prompts", "owner_agent_id"),
    ("agent_prompts", "agent_id"),
    ("agent_versions", "agent_id"),
)


def _data() -> dict[str, list[dict]]:
    return json.loads(_DATA_PATH.read_text())


def _agent_ids(data: dict[str, list[dict]]) -> list[int]:
    return sorted(row["id"] for row in data["agents"])


def _live_rows(conn, table: str, column: str, agent_ids: list[int]) -> list[dict]:
    raw = conn.execute(
        text(
            f"SELECT coalesce(json_agg(row_to_json(x) ORDER BY x.id), '[]'::json) "  # fixed table names
            f"FROM {table} x WHERE {column} = ANY(:ids)"
        ),
        {"ids": agent_ids},
    ).scalar_one()
    return raw if isinstance(raw, list) else json.loads(raw)


def _fresh_bootstrap() -> bool:
    """True when this run builds an empty database from base (see alembic/env.py)."""
    config = getattr(op.get_context(), "config", None)
    return bool(config is not None and config.attributes.get("fresh_bootstrap"))


def upgrade() -> None:
    if _fresh_bootstrap():
        # No production data exists to transform; the seed supplies current rows.
        return
    conn = op.get_bind()
    data = _data()
    agent_ids = _agent_ids(data)
    conn.execute(text("SELECT id FROM agents WHERE id = ANY(:ids) FOR UPDATE"), {"ids": agent_ids})
    for table, column in _TABLES:
        if _live_rows(conn, table, column, agent_ids) != data[table]:
            raise RuntimeError(f"{table} rows for the inactive agents differ from the recorded preimage")
    conn.execute(text("DELETE FROM agents WHERE id = ANY(:ids) AND is_active = false"), {"ids": agent_ids})


def downgrade() -> None:
    conn = op.get_bind()
    data = _data()
    agent_ids = _agent_ids(data)
    if conn.execute(text("SELECT count(*) FROM agents WHERE id = ANY(:ids)"), {"ids": agent_ids}).scalar_one():
        raise RuntimeError("an agent id from the deleted set exists again; refusing to overwrite it")
    for table, _column in _TABLES:
        conn.execute(
            text(
                f"INSERT INTO {table} SELECT * FROM json_populate_recordset(NULL::{table}, CAST(:rows AS json))"
            ),
            {"rows": json.dumps(data[table])},
        )
