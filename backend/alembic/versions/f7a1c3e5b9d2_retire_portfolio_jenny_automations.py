"""Retire Portfolio AI's Jenny investing automations and unused Portfolio prompts.

Revision ID: f7a1c3e5b9d2
Revises: d3a9c1f47e20

Portfolio AI is removing Jenny's investing side (value audit W9): the daily
operator, weekly learning and the long-gone ML retrain. This deletes the
portfolio-ai/jenny_daily_operator, portfolio-ai/jenny_weekly_learning and
portfolio-ai/retrain_ml definitions, their profiles (revisions cascade) and
their terminal runs, plus five Portfolio prompts nothing calls any more
(portfolio-jenny-chat-system, portfolio-jenny-planning-extract-system,
portfolio-jenny-reconcile-system and both portfolio-article-quality-labeling
prompts). Household maintenance and the weekly price check stay.

The sibling .json file holds the exact preimage of the definitions, profiles,
profile revisions and prompts, plus the run ids: upgrade refuses unless the
live rows still match it. Run receipts carry household data, so they are kept
out of the repository; the full rows were archived to
backups/2026-10-16-portfolio-jenny-retirement before this ran. Downgrade
restores everything except the runs.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import text

from alembic import op

revision: str = "f7a1c3e5b9d2"
down_revision: str | Sequence[str] | None = "d3a9c1f47e20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATA_PATH = Path(__file__).with_suffix(".json")
# Restore order: parents before the rows that reference them.
_RESTORE = (
    "automation_definitions",
    "automation_profiles",
    "automation_profile_revisions",
    "prompts",
)
_TERMINAL = ("succeeded", "failed", "skipped", "cancelled")


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
    run_ids = sorted(data["automation_run_ids"])
    slugs = _ids(data["prompts"], "slug")
    prompt_ids = _ids(data["prompts"], "id")

    # A database that never held these exact rows (a test or scratch copy) has
    # nothing to retire; a partial match still refuses below.
    if not conn.execute(
        text(
            "SELECT (SELECT count(*) FROM automation_profiles WHERE id = ANY(:pids))"
            " + (SELECT count(*) FROM automation_runs WHERE id = ANY(:rids))"
            " + (SELECT count(*) FROM prompts WHERE id = ANY(:ids) AND slug = ANY(:s))"
        ),
        {"pids": profile_ids, "rids": run_ids, "ids": prompt_ids, "s": slugs},
    ).scalar_one():
        return

    live_profiles = conn.execute(
        text("SELECT id FROM automation_profiles WHERE workflow_key = ANY(:k) ORDER BY id FOR UPDATE"),
        {"k": keys},
    ).scalars().all()
    if sorted(live_profiles) != profile_ids:
        raise RuntimeError("retired Portfolio automation profiles differ from the recorded preimage")
    live_runs = conn.execute(
        text(
            "SELECT id, status FROM automation_runs "
            "WHERE workflow_key = ANY(:k) OR profile_id = ANY(:ids) FOR UPDATE"
        ),
        {"k": keys, "ids": profile_ids},
    ).all()
    if sorted(row.id for row in live_runs) != run_ids:
        raise RuntimeError("retired Portfolio automations gained runs; refusing to delete them")
    if any(row.status not in _TERMINAL for row in live_runs):
        raise RuntimeError("a retired Portfolio automation run is still open; refusing to delete it")
    live_prompts = conn.execute(
        text("SELECT id FROM prompts WHERE slug = ANY(:s) ORDER BY id FOR UPDATE"), {"s": slugs}
    ).scalars().all()
    if sorted(live_prompts) != prompt_ids:
        raise RuntimeError("retired Portfolio prompts differ from the recorded preimage")
    if conn.execute(
        text("SELECT count(*) FROM agent_prompts WHERE prompt_id = ANY(:ids)"), {"ids": prompt_ids}
    ).scalar_one():
        raise RuntimeError("a retired Portfolio prompt is assigned to an agent; refusing to delete it")

    conn.execute(text("DELETE FROM automation_runs WHERE id = ANY(:ids)"), {"ids": run_ids})
    conn.execute(text("DELETE FROM automation_profiles WHERE id = ANY(:ids)"), {"ids": profile_ids})
    conn.execute(text("DELETE FROM automation_definitions WHERE workflow_key = ANY(:k)"), {"k": keys})
    # prompt_revisions.prompt_id is ON DELETE SET NULL; downgrade relinks them.
    conn.execute(text("DELETE FROM prompts WHERE id = ANY(:ids)"), {"ids": prompt_ids})


def downgrade() -> None:
    conn = op.get_bind()
    data = _data()
    if conn.execute(
        text("SELECT count(*) FROM automation_definitions WHERE workflow_key = ANY(:k)"),
        {"k": _ids(data["automation_definitions"], "workflow_key")},
    ).scalar_one() or conn.execute(
        text("SELECT count(*) FROM prompts WHERE slug = ANY(:s)"), {"s": _ids(data["prompts"], "slug")}
    ).scalar_one():
        raise RuntimeError("a retired Portfolio definition or prompt exists again; refusing to overwrite it")
    for table in _RESTORE:
        conn.execute(
            text(f"INSERT INTO {table} SELECT * FROM json_populate_recordset(NULL::{table}, CAST(:rows AS json))"),
            {"rows": json.dumps(data[table])},
        )
    for link in data["prompt_revision_links"]:
        conn.execute(
            text("UPDATE prompt_revisions SET prompt_id = :prompt_id WHERE id = :id AND prompt_id IS NULL"),
            link,
        )
