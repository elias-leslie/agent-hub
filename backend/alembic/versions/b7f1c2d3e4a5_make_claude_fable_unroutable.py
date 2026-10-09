"""Make Claude Fable 5.1 unroutable.

Revision ID: b7f1c2d3e4a5
Revises: 43f0a2fd606f

The owner keeps Fable 5.1 off every agent route. The row stays catalogued but
inactive, so routing skips it, agent assignments reject it, and its alias
resolves to a clear "inactive" reason instead of an unknown model.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "b7f1c2d3e4a5"
down_revision: str | Sequence[str] | None = "43f0a2fd606f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FABLE = "claude-fable-5-1"
_BEFORE = {
    "is_active": True,
    "hint": "Most capable Claude; scores inherited from Opus 4.7",
    "availability": "claude_code_cli_subscription; verified_2026-10-09; prices_platform.claude.com_2026-10-09",
}
_AFTER = {
    "is_active": False,
    "hint": "Unroutable by owner policy; no agent may use it",
    "availability": "owner_policy_unroutable_2026-10-09; claude_code_cli_subscription",
}


def _route_references() -> list[str]:
    rows = op.get_bind().execute(
        text(
            "SELECT slug FROM agents WHERE primary_model_id = :m OR escalation_model_id = :m "
            "OR CAST(fallback_models AS TEXT) LIKE :quoted"
        ),
        {"m": _FABLE, "quoted": f'%"{_FABLE}"%'},
    )
    return [row[0] for row in rows]


def _swap(expected: dict, target: dict) -> None:
    conn = op.get_bind()
    current = conn.execute(
        text("SELECT is_active, hint, availability FROM models WHERE id = :id FOR UPDATE"), {"id": _FABLE}
    ).mappings().one()
    if dict(current) != expected:
        raise RuntimeError(f"Model '{_FABLE}' has an unknown catalog revision")
    conn.execute(
        text("UPDATE models SET is_active = :is_active, hint = :hint, availability = :availability, updated_at = NOW() WHERE id = :id"),
        {"id": _FABLE, **target},
    )


def _fresh_bootstrap() -> bool:
    """True when this run builds an empty database from base (see alembic/env.py)."""
    config = getattr(op.get_context(), "config", None)
    return bool(config is not None and config.attributes.get("fresh_bootstrap"))


def upgrade() -> None:
    if _fresh_bootstrap():
        # No production data exists to transform; the seed supplies current rows.
        return
    if referenced := _route_references():
        raise RuntimeError(f"Agents still route to {_FABLE}: {referenced}")
    _swap(_BEFORE, _AFTER)


def downgrade() -> None:
    _swap(_AFTER, _BEFORE)
