"""Retire Portfolio AI's insight cross-validation prompts.

Revision ID: c5e8a2d4f1b7
Revises: f7a1c3e5b9d2

Portfolio AI removed insight cross-validation along with the rest of Jenny's
investing side (portfolio-ai 1246b76d1), so nothing calls
portfolio-cross-validation-review-system or
portfolio-cross-validation-review-template any more. This deletes both.

The sibling .json file holds the exact preimage of the two prompt rows and
their revision links: upgrade refuses unless the live rows still match it,
and does nothing where neither prompt exists. Downgrade restores both
prompts and relinks their revisions.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import text

from alembic import op

revision: str = "c5e8a2d4f1b7"
down_revision: str | Sequence[str] | None = "f7a1c3e5b9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATA_PATH = Path(__file__).with_suffix(".json")


def _data() -> dict:
    return json.loads(_DATA_PATH.read_text())


def _fresh_bootstrap() -> bool:
    """True when this run builds an empty database from base (see alembic/env.py)."""
    config = getattr(op.get_context(), "config", None)
    return bool(config is not None and config.attributes.get("fresh_bootstrap"))


def upgrade() -> None:
    if _fresh_bootstrap():
        return
    conn = op.get_bind()
    data = _data()
    recorded = sorted((row["id"], row["slug"], row["content"]) for row in data["prompts"])
    prompt_ids = [row[0] for row in recorded]
    links = sorted((link["id"], link["prompt_id"]) for link in data["prompt_revision_links"])

    live_prompts = conn.execute(
        text("SELECT id, slug, content FROM prompts WHERE slug = ANY(:s) ORDER BY id FOR UPDATE"),
        {"s": [row[1] for row in recorded]},
    ).all()
    if not live_prompts:
        return  # already gone (or never seeded here): nothing to retire
    if sorted(tuple(row) for row in live_prompts) != recorded or not conn.execute(
        text(
            "SELECT (SELECT jsonb_agg(to_jsonb(p) ORDER BY p.id) FROM prompts p WHERE p.id = ANY(:ids))"
            " IS NOT DISTINCT FROM (SELECT jsonb_agg(to_jsonb(r) ORDER BY r.id)"
            " FROM json_populate_recordset(NULL::prompts, CAST(:rows AS json)) r)"
        ),
        {"ids": prompt_ids, "rows": json.dumps(data["prompts"])},
    ).scalar_one():
        # Every column must match, so downgrade restores exactly what upgrade deleted.
        raise RuntimeError("retired cross-validation prompts differ from the recorded preimage")
    live_links = conn.execute(
        text("SELECT CAST(id AS text), prompt_id FROM prompt_revisions WHERE prompt_id = ANY(:ids) FOR UPDATE"),
        {"ids": prompt_ids},
    ).all()
    if sorted(tuple(row) for row in live_links) != links:
        raise RuntimeError("retired cross-validation prompts gained revisions; refusing to delete them")
    if conn.execute(
        text("SELECT count(*) FROM agent_prompts WHERE prompt_id = ANY(:ids)"), {"ids": prompt_ids}
    ).scalar_one():
        raise RuntimeError("a retired cross-validation prompt is assigned to an agent; refusing to delete it")

    # prompt_revisions.prompt_id is ON DELETE SET NULL; downgrade relinks them.
    conn.execute(text("DELETE FROM prompts WHERE id = ANY(:ids)"), {"ids": prompt_ids})


def downgrade() -> None:
    conn = op.get_bind()
    data = _data()
    if conn.execute(
        text("SELECT count(*) FROM prompts WHERE slug = ANY(:s) OR id = ANY(:ids)"),
        {"s": [row["slug"] for row in data["prompts"]], "ids": [row["id"] for row in data["prompts"]]},
    ).scalar_one():
        raise RuntimeError("a retired cross-validation prompt exists again; refusing to overwrite it")
    conn.execute(
        text("INSERT INTO prompts SELECT * FROM json_populate_recordset(NULL::prompts, CAST(:rows AS json))"),
        {"rows": json.dumps(data["prompts"])},
    )
    for link in data["prompt_revision_links"]:
        conn.execute(
            text("UPDATE prompt_revisions SET prompt_id = :prompt_id WHERE id = :id AND prompt_id IS NULL"),
            link,
        )
