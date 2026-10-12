"""Retire persona automations and deactivate test API keys (value audit Stage 3).

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6

The persona heartbeat, scheduler and job workflows were removed in Stage 3 of
the October 2026 value audit. This deletes their automation
definitions, profiles (revisions cascade) and schedule controls, and
deactivates the 127 never-used test API keys. The sibling .json file holds the
exact preimage: upgrade refuses to run unless the identifying rows still match
it, and downgrade restores every row with its original id and reactivates the
recorded keys. Key hashes are not stored.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import text

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATA_PATH = Path(__file__).with_suffix(".json")
# Restore order: parents before the rows that reference them.
_RESTORE = (
    "automation_definitions",
    "automation_profiles",
    "automation_profile_revisions",
    "workflow_schedule_controls",
)


def _data() -> dict:
    return json.loads(_DATA_PATH.read_text())


def _fresh_bootstrap() -> bool:
    """True when this run builds an empty database from base (see alembic/env.py)."""
    config = getattr(op.get_context(), "config", None)
    return bool(config is not None and config.attributes.get("fresh_bootstrap"))


def _ids(rows: list[dict], key: str) -> list:
    return sorted(row[key] for row in rows)


def upgrade() -> None:
    if _fresh_bootstrap():
        return
    conn = op.get_bind()
    data = _data()
    keys = _ids(data["automation_definitions"], "workflow_key")
    profile_ids = _ids(data["automation_profiles"], "id")
    schedule_ids = _ids(data["workflow_schedule_controls"], "schedule_id")
    key_ids = sorted(data["api_keys_active_ids"])

    live_profiles = conn.execute(
        text("SELECT id FROM automation_profiles WHERE workflow_key = ANY(:k) ORDER BY id FOR UPDATE"),
        {"k": keys},
    ).scalars().all()
    if sorted(live_profiles) != profile_ids:
        raise RuntimeError("persona automation profiles differ from the recorded preimage")
    if conn.execute(
        text("SELECT count(*) FROM automation_profiles WHERE id = ANY(:ids) AND enabled"), {"ids": profile_ids}
    ).scalar_one():
        raise RuntimeError("a persona automation profile was re-enabled; refusing to delete it")
    if conn.execute(
        text("SELECT count(*) FROM automation_runs WHERE profile_id = ANY(:ids)"), {"ids": profile_ids}
    ).scalar_one():
        raise RuntimeError("persona automation profiles gained runs; refusing to delete them")
    if conn.execute(
        text("SELECT count(*) FROM api_keys WHERE id = ANY(:ids) AND last_used_at IS NOT NULL"), {"ids": key_ids}
    ).scalar_one():
        raise RuntimeError("a recorded test API key has been used; refusing to deactivate it")

    conn.execute(text("DELETE FROM automation_profiles WHERE id = ANY(:ids)"), {"ids": profile_ids})
    conn.execute(text("DELETE FROM automation_definitions WHERE workflow_key = ANY(:k)"), {"k": keys})
    conn.execute(text("DELETE FROM workflow_schedule_controls WHERE schedule_id = ANY(:s)"), {"s": schedule_ids})
    conn.execute(text("UPDATE api_keys SET is_active = 0 WHERE id = ANY(:ids)"), {"ids": key_ids})


def downgrade() -> None:
    conn = op.get_bind()
    data = _data()
    if conn.execute(
        text("SELECT count(*) FROM automation_definitions WHERE workflow_key = ANY(:k)"),
        {"k": _ids(data["automation_definitions"], "workflow_key")},
    ).scalar_one():
        raise RuntimeError("a retired persona automation definition exists again; refusing to overwrite it")
    for table in _RESTORE:
        conn.execute(
            text(f"INSERT INTO {table} SELECT * FROM json_populate_recordset(NULL::{table}, CAST(:rows AS json))"),
            {"rows": json.dumps(data[table])},
        )
    conn.execute(
        text("UPDATE api_keys SET is_active = 1 WHERE id = ANY(:ids)"), {"ids": sorted(data["api_keys_active_ids"])}
    )
