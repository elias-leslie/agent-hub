"""Redact credentials already stored in session transcripts.

Revision ID: b6850500dbfd
Revises: c4f8a2e6d1b3

New session events, memories and revisions pass the secret floor
(app.services.secret_redaction) on every write. This applies the same floor
once to existing session_events rows (owner decision 4, 2026-10-15). A cheap
PostgreSQL regex preselects candidates; the floor itself decides, so only rows
it changes are rewritten. Only ids and per-kind counts are logged, never the
matched text. The original rows were backed up outside the database before this
ran, so downgrade does not restore them.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op
from app.services.secret_redaction import redact_secrets

revision = "b6850500dbfd"
down_revision = "c4f8a2e6d1b3"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# Superset of the floor: each pattern's fixed prefix plus its minimum length.
CANDIDATE_REGEX = (
    r"(-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36}"
    r"|github_pat_[A-Za-z0-9_]{22}|glpat-[A-Za-z0-9_-]{20}|xox[abposr]-[A-Za-z0-9-]{10}"
    r"|sk-ant-[A-Za-z0-9_-]{20}|[rs]k_live_[A-Za-z0-9]{20})"
)


def _events() -> sa.TableClause:
    return sa.table(
        "session_events",
        sa.column("id", UUID(as_uuid=False)),
        sa.column("content", sa.Text),
        sa.column("tool_input", JSONB),
        sa.column("tool_output", JSONB),
    )


def _candidate_predicate(events: sa.TableClause):
    return sa.or_(
        events.c.content.op("~")(CANDIDATE_REGEX),
        sa.cast(events.c.tool_input, sa.Text).op("~")(CANDIDATE_REGEX),
        sa.cast(events.c.tool_output, sa.Text).op("~")(CANDIDATE_REGEX),
    )


def _redact(value: Any, kinds: Counter[str]) -> Any:
    if isinstance(value, str):
        redacted, counts = redact_secrets(value)
        kinds.update(counts)
        return redacted if counts else value
    if isinstance(value, list):
        return [_redact(item, kinds) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, kinds) for key, item in value.items()}
    return value


def redact_rows(bind: sa.Connection) -> tuple[list[str], Counter[str]]:
    """Rewrite every candidate row the floor changes; return ids and kind counts."""
    events = _events()
    rows = bind.execute(
        sa.select(events.c.id, events.c.content, events.c.tool_input, events.c.tool_output)
        .where(_candidate_predicate(events))
        .order_by(events.c.id)
    ).all()
    changed: list[str] = []
    totals: Counter[str] = Counter()
    for row in rows:
        kinds: Counter[str] = Counter()
        values: dict[str, Any] = {}
        for column in ("content", "tool_input", "tool_output"):
            before = sum(kinds.values())
            redacted = _redact(getattr(row, column), kinds)
            # Untouched columns stay out of the UPDATE (a JSONB NULL must not become 'null').
            if sum(kinds.values()) > before:
                values[column] = redacted
        if not values:
            continue
        bind.execute(events.update().where(events.c.id == row.id).values(**values))
        changed.append(str(row.id))
        totals.update(kinds)
    return changed, totals


def upgrade() -> None:
    changed, totals = redact_rows(op.get_bind())
    logger.info(
        "Secret redaction: rows=%d kinds=%s ids=%s",
        len(changed), dict(sorted(totals.items())), ",".join(changed),
    )


def downgrade() -> None:
    # Irreversible by design: restoring would put the credentials back.
    pass
