"""Pin Daybreak Blue requests before the October 28 alias retirement.

Revision ID: a2d6b8e1f930
Revises: 6c1d7434cb40

The account advertises daybreak_blue for gpt-5.6-sol. Keep the existing role,
subscription cost and access program; only the provider model becomes explicit.
https://developers.openai.com/api/docs/guides/daybreak

Current routes and the local codex-daybreak shortcut move to the pinned entry.
Historical sessions, receipts, prompts, benchmarks and accounting stay intact.
The old catalog row remains inactive for historical lookup.
"""

from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "a2d6b8e1f930"
down_revision = "6c1d7434cb40"
branch_labels = None
depends_on = None

_OLD = "codex/gpt-daybreak-blue-latest"
_NEW = "codex/gpt-5.6-sol-daybreak-blue"
_AVAILABILITY = (
    "codex_oauth_subscription; pinned_gpt-5.6-sol; "
    "needs_access_programs_cyber_daybreak_blue"
)


def _move_routes(conn, source: str, target: str) -> None:
    rows = conn.execute(sa.text(
        "SELECT slug, primary_model_id, fallback_models, escalation_model_id "
        "FROM agents WHERE primary_model_id = :source OR escalation_model_id = :source "
        "OR CAST(fallback_models AS TEXT) LIKE :quoted FOR UPDATE"
    ), {"source": source, "quoted": f'%"{source}"%'}).mappings()
    for row in rows:
        conn.execute(sa.text(
            "UPDATE agents SET primary_model_id = :primary, "
            "fallback_models = CAST(:fallbacks AS JSON), escalation_model_id = :escalation, "
            "version = version + 1, updated_at = NOW() WHERE slug = :slug"
        ), {
            "slug": row["slug"],
            "primary": target if row["primary_model_id"] == source else row["primary_model_id"],
            "fallbacks": json.dumps([
                target if model == source else model for model in row["fallback_models"] or []
            ]),
            "escalation": target if row["escalation_model_id"] == source else row["escalation_model_id"],
        })
    conn.execute(sa.text(
        "UPDATE model_aliases SET model_id = :target, updated_at = NOW() WHERE model_id = :source"
    ), {"source": source, "target": target})


def upgrade() -> None:
    config = getattr(op.get_context(), "config", None)
    if config is not None and config.attributes.get("fresh_bootstrap"):
        return  # The current seed supplies the pinned entry on an empty DB.
    conn = op.get_bind()
    models = sa.Table("models", sa.MetaData(), autoload_with=conn)
    previous = conn.execute(
        sa.select(models).where(models.c.id == _OLD).with_for_update()
    ).mappings().one_or_none()
    if previous is None:
        referenced = conn.execute(sa.text(
            "SELECT 1 FROM model_aliases WHERE model_id = :old UNION ALL "
            "SELECT 1 FROM agents WHERE primary_model_id = :old OR escalation_model_id = :old "
            "OR CAST(fallback_models AS TEXT) LIKE :quoted LIMIT 1"
        ), {"old": _OLD, "quoted": f'%"{_OLD}"%'}).first()
        if referenced:
            raise RuntimeError("Daybreak routes exist without their catalog entry")
        return  # An unseeded catalog is populated from the current seed at startup.
    if (
        previous["provider"] != "codex"
        or not previous["is_active"]
        or previous["upstream_id"] is not None
        or previous["access_programs"] != {"cyber": "daybreak_blue"}
    ):
        raise RuntimeError("Daybreak Blue catalog entry has changed; preserve its current settings")
    pinned = {key: value for key, value in previous.items() if key not in {"created_at", "updated_at"}}
    pinned.update(id=_NEW, upstream_id="gpt-5.6-sol", availability=_AVAILABILITY)
    existing = conn.execute(sa.select(models).where(models.c.id == _NEW)).mappings().one_or_none()
    if existing is None:
        conn.execute(models.insert().values(**pinned))
    elif existing["is_active"] or any(
        existing[key] != value for key, value in pinned.items() if key != "is_active"
    ):
        raise RuntimeError("Pinned Daybreak Blue catalog entry has changed")
    else:
        conn.execute(models.update().where(models.c.id == _NEW).values(is_active=True))
    _move_routes(conn, _OLD, _NEW)
    conn.execute(models.update().where(models.c.id == _OLD).values(is_active=False))


def downgrade() -> None:
    conn = op.get_bind()
    _move_routes(conn, _NEW, _OLD)
    conn.execute(sa.text("UPDATE models SET is_active = TRUE, updated_at = NOW() WHERE id = :id"), {"id": _OLD})
    conn.execute(sa.text("UPDATE models SET is_active = FALSE, updated_at = NOW() WHERE id = :id"), {"id": _NEW})
