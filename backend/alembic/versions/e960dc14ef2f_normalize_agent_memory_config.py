"""normalize agent memory config

Revision ID: e960dc14ef2f
Revises: b217f2377552
Create Date: 2026-03-24 22:51:39.022874

"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e960dc14ef2f'
down_revision: str | Sequence[str] | None = 'b217f2377552'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CANONICAL_BOOL_KEYS = {
    "injection_enabled",
    "include_mandates",
    "include_guardrails",
    "include_references",
    "continuity_enabled",
}
_CANONICAL_LIST_KEYS = {"audience_tags", "exclude_tags"}
_CANONICAL_INT_DEFAULTS = {"continuity_max_sessions": 5}
_LEGACY_KEYS = {"enabled"}


def _coerce_bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _coerce_int(value: Any, default: int, *, minimum: int = 1) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(value, minimum)
    return default


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _normalize_memory_config(memory_config: dict[str, Any]) -> dict[str, Any]:
    raw = dict(memory_config)
    extras = {
        key: value
        for key, value in raw.items()
        if key not in _CANONICAL_BOOL_KEYS
        and key not in _CANONICAL_LIST_KEYS
        and key not in _CANONICAL_INT_DEFAULTS
        and key not in _LEGACY_KEYS
    }
    enabled = _coerce_bool(raw.get("enabled"), True)
    return {
        **extras,
        "injection_enabled": enabled and _coerce_bool(raw.get("injection_enabled"), True),
        "include_mandates": _coerce_bool(raw.get("include_mandates"), True),
        "include_guardrails": _coerce_bool(raw.get("include_guardrails"), True),
        "include_references": _coerce_bool(raw.get("include_references"), True),
        "continuity_enabled": _coerce_bool(raw.get("continuity_enabled"), True),
        "continuity_max_sessions": _coerce_int(raw.get("continuity_max_sessions"), 5),
        "audience_tags": _normalize_string_list(raw.get("audience_tags")),
        "exclude_tags": _normalize_string_list(raw.get("exclude_tags")),
    }


def upgrade() -> None:
    """Materialize canonical memory_config objects for all custom agent rows."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, memory_config
              FROM agents
             WHERE memory_config IS NOT NULL
            """
        )
    ).mappings()

    for row in rows:
        raw = row["memory_config"]
        if not isinstance(raw, dict):
            bind.execute(
                sa.text(
                    """
                    UPDATE agents
                       SET memory_config = NULL
                     WHERE id = :agent_id
                    """
                ),
                {"agent_id": row["id"]},
            )
            continue
        normalized = _normalize_memory_config(raw)
        if normalized == raw:
            continue
        bind.execute(
            sa.text(
                """
                UPDATE agents
                   SET memory_config = CAST(:memory_config AS JSONB)
                 WHERE id = :agent_id
                """
            ),
            {
                "agent_id": row["id"],
                "memory_config": json.dumps(normalized),
            },
        )


def downgrade() -> None:
    """Irreversible data normalization migration."""
    # The prior sparse shape cannot be reconstructed reliably.
