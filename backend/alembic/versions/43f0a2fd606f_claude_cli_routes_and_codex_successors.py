"""Route Claude through the CLI, retire gpt-5.5 and Claude 4.x, fix Daybreak Blue.

Revision ID: 43f0a2fd606f
Revises: ac0650fc9388

Live evidence on 2026-10-09:

* The Codex models endpoint marks gpt-5.5 as retiring 2026-10-14 with
  gpt-6.1-sol as its upgrade. GPT-5.6 Sol/Terra/Luna are listed as "older"
  generation; the 6.x equivalents cost the same or less (OpenAI API pricing).
* gpt-daybreak-blue-latest is listed (not hidden) as Codex's defensive
  cybersecurity model, and the API rejects it with explicit
  ``access_programs.cyber`` values other than ``daybreak_blue``. OpenAI's API
  docs deprecate the API alias; the Codex route does not expose a snapshot.
* Claude runs through the headless Claude Code CLI on the owner's Max
  subscription. Claude 5.x prices and limits come from platform.claude.com.
* Kimi Code (403, subscription lacks the product) and MiniMax (402, zero
  balance) stay catalogued but inactive so credentials can be stored and the
  rows re-enabled after a top-up.

The exact preimage and postimage live in the sibling .json data file. Upgrade
refuses to run against any other revision of a touched row; downgrade restores
every deleted row, alias, changed column and agent route, then drops
``models.access_programs``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "43f0a2fd606f"
down_revision: str | Sequence[str] | None = "ac0650fc9388"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATA_PATH = Path(__file__).with_suffix(".json")
_ROUTE_COLUMNS = ("primary_model_id", "fallback_models", "escalation_model_id", "is_active")
_JSONB_COLUMNS = frozenset({"service_tiers", "thinking_level_map", "access_programs"})


def _data() -> dict:
    return json.loads(_DATA_PATH.read_text())


def _unknown(subject: str) -> RuntimeError:
    return RuntimeError(f"{subject} has an unknown model-migration revision")


def _model_row(conn, model_id: str) -> dict | None:
    row = conn.execute(
        text("SELECT * FROM models WHERE id = :id FOR UPDATE"), {"id": model_id}
    ).mappings().one_or_none()
    if row is None:
        return None
    return {k: v for k, v in row.items() if k not in ("created_at", "updated_at")}


def _aliases_for(conn, model_ids: list[str]) -> list[dict]:
    rows = conn.execute(
        text("SELECT alias, model_id, alias_type, source FROM model_aliases WHERE model_id = ANY(:ids)"),
        {"ids": model_ids},
    ).mappings()
    return sorted((dict(r) for r in rows), key=lambda r: r["alias"])


def _bind(column: str) -> str:
    return f"CAST(:{column} AS JSONB)" if column in _JSONB_COLUMNS else f":{column}"


def _params(values: dict) -> dict:
    return {c: json.dumps(v) if c in _JSONB_COLUMNS and v is not None else v for c, v in values.items()}


def _insert_model(conn, row: dict) -> None:
    columns = list(row)
    conn.execute(
        text(f"INSERT INTO models ({', '.join(columns)}) VALUES ({', '.join(_bind(c) for c in columns)})"),
        _params(row),
    )


def _insert_alias(conn, alias: dict) -> None:
    conn.execute(
        text("INSERT INTO model_aliases (alias, model_id, alias_type, source) VALUES (:alias, :model_id, :alias_type, :source)"),
        alias,
    )


def _replace_models(conn, remove: list[dict], add: list[dict], remove_aliases: list[dict]) -> None:
    """Delete exact ``remove`` rows (aliases cascade) and insert ``add`` rows."""
    for row in remove:
        if _model_row(conn, row["id"]) != row:
            raise _unknown(f"Model '{row['id']}'")
    if _aliases_for(conn, [r["id"] for r in remove]) != remove_aliases:
        raise _unknown("Aliases of removed models")
    for row in add:
        if _model_row(conn, row["id"]) is not None:
            raise _unknown(f"Model '{row['id']}'")
    conn.execute(text("DELETE FROM models WHERE id = ANY(:ids)"), {"ids": [r["id"] for r in remove]})
    for row in add:
        _insert_model(conn, row)


def _update_models(conn, updates: dict, *, reverse: bool) -> None:
    src, dst = ("after", "before") if reverse else ("before", "after")
    for model_id, changes in updates.items():
        current = _model_row(conn, model_id)
        if current is None or any(current[c] != v[src] for c, v in changes.items()):
            raise _unknown(f"Model '{model_id}'")
        assignments = ", ".join(f"{c} = {_bind(c)}" for c in changes)
        conn.execute(
            text(f"UPDATE models SET {assignments}, updated_at = NOW() WHERE id = :id"),
            {**_params({c: v[dst] for c, v in changes.items()}), "id": model_id},
        )


def _check_route(slug: str, current: dict, expected: dict) -> None:
    actual = {c: current[c] for c in _ROUTE_COLUMNS}
    actual["fallback_models"] = actual["fallback_models"] or []
    if actual != {**expected, "fallback_models": expected["fallback_models"] or []}:
        raise _unknown(f"Agent '{slug}'")


def _set_routes(conn, routes: dict, *, reverse: bool) -> None:
    src, dst = ("after", "before") if reverse else ("before", "after")
    for slug, route in routes.items():
        current = conn.execute(
            text("SELECT primary_model_id, fallback_models, escalation_model_id, is_active FROM agents WHERE slug = :slug FOR UPDATE"),
            {"slug": slug},
        ).mappings().one()
        _check_route(slug, dict(current), route[src])
        target = route[dst]
        conn.execute(
            text(
                "UPDATE agents SET primary_model_id = :primary_model_id, "
                "fallback_models = CAST(:fallback_models AS JSON), "
                "escalation_model_id = :escalation_model_id, is_active = :is_active, "
                "version = version + 1, updated_at = NOW() WHERE slug = :slug"
            ),
            {**target, "fallback_models": json.dumps(target["fallback_models"]), "slug": slug},
        )


def _fresh_bootstrap() -> bool:
    """True when this run builds an empty database from base (see alembic/env.py)."""
    config = getattr(op.get_context(), "config", None)
    return bool(config is not None and config.attributes.get("fresh_bootstrap"))


def upgrade() -> None:
    if _fresh_bootstrap():
        # No production data exists to transform; the seed supplies current rows.
        return
    op.add_column("models", sa.Column("access_programs", JSONB(), nullable=True))
    conn = op.get_bind()
    data = _data()
    _replace_models(conn, data["deleted_models"], data["new_models"], data["deleted_aliases"])
    for alias in data["new_aliases"]:
        _insert_alias(conn, alias)
    _update_models(conn, data["updated_models"], reverse=False)
    _set_routes(conn, data["routes"], reverse=False)


def downgrade() -> None:
    conn = op.get_bind()
    data = _data()
    _set_routes(conn, data["routes"], reverse=True)
    _update_models(conn, data["updated_models"], reverse=True)
    new_ids = [r["id"] for r in data["new_models"]]
    new_aliases = sorted(data["new_aliases"], key=lambda a: a["alias"])
    if _aliases_for(conn, new_ids) != new_aliases:
        raise _unknown("Aliases of added models")
    conn.execute(
        text("DELETE FROM model_aliases WHERE alias = ANY(:aliases)"),
        {"aliases": [a["alias"] for a in new_aliases]},
    )
    _replace_models(conn, data["new_models"], data["deleted_models"], [])
    for alias in data["deleted_aliases"]:
        _insert_alias(conn, alias)
    op.drop_column("models", "access_programs")
