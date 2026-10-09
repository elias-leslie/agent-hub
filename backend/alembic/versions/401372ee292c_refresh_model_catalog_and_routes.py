"""Refresh the model catalog and repoint agents to servable models.

Revision ID: 401372ee292c
Revises: 7e31a9c4f602

Live servability probes on 2026-10-09 (Agent Hub provider-liveness-probe and
direct provider calls with the stored credentials):

* Codex rejects gpt-5.1/5.2/5.3-codex, spark, gpt-5.4 and gpt-5.4-mini on the
  ChatGPT-account login ("not supported with a ChatGPT account"). Its models
  endpoint lists gpt-6.1-sol, gpt-6-astra, gpt-6-sol, gpt-6-luna,
  gpt-5.6-sol/terra/luna, gpt-daybreak-blue-latest and gpt-5.5 (hidden legacy),
  all with a 272k context window.
* NVIDIA NIM returns 410 (EOL) for glm-5.2, gpt-oss-120b, minimax-m3 and
  deepseek-v4-flash-0731, and 404 for flux.1-schnell and sd-3.5-large.
* Cloudflare Workers Free does not serve the Kimi models; FLUX.2-dev returns 500.
* No stored credential exists for openai, moonshot, deepseek or zhipu. The
  kimi-code subscription lacks Kimi Code (403), the MiniMax key has no balance
  (402) and OpenRouter has no free slugs or credits left.
* Gemini 2.5 Pro, 3.1 Pro and the image models have no quota on our keys.

The exact preimage and postimage live in the sibling .json data file:
rows generated from the live DB (before) and MODEL_CATALOG (after). Upgrade
refuses to run against any other revision of a touched row; downgrade restores
every deleted row, alias, changed column and agent route.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import text

from alembic import op

revision: str = "401372ee292c"
down_revision: str | Sequence[str] | None = "7e31a9c4f602"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATA_PATH = Path(__file__).with_suffix(".json")
_ROUTE_COLUMNS = ("primary_model_id", "fallback_models", "escalation_model_id", "is_active")


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


def _insert_model(conn, row: dict) -> None:
    columns = list(row)
    values = ", ".join(
        "CAST(:service_tiers AS JSONB)" if c == "service_tiers" else f":{c}" for c in columns
    )
    conn.execute(
        text(f"INSERT INTO models ({', '.join(columns)}) VALUES ({values})"),
        {**row, "service_tiers": json.dumps(row["service_tiers"])},
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
        assignments = ", ".join(
            f"{c} = CAST(:{c} AS JSONB)" if c == "service_tiers" else f"{c} = :{c}" for c in changes
        )
        params = {c: v[dst] for c, v in changes.items()}
        if "service_tiers" in params:
            params["service_tiers"] = json.dumps(params["service_tiers"])
        conn.execute(
            text(f"UPDATE models SET {assignments}, updated_at = NOW() WHERE id = :id"),
            {**params, "id": model_id},
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
    new_aliases = sorted(data["new_aliases"], key=lambda a: a["alias"])
    if _aliases_for(conn, [r["id"] for r in data["new_models"]]) != [
        a for a in new_aliases if a["model_id"] in {r["id"] for r in data["new_models"]}
    ]:
        raise _unknown("Aliases of added models")
    conn.execute(
        text("DELETE FROM model_aliases WHERE alias = ANY(:aliases)"),
        {"aliases": [a["alias"] for a in new_aliases]},
    )
    _replace_models(conn, data["new_models"], data["deleted_models"], [])
    for alias in data["deleted_aliases"]:
        _insert_alias(conn, alias)
