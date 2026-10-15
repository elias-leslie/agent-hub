"""Redact credentials already stored in memory and revision text or metadata.

Revision ID: d3a9c1f47e20
Revises: b6850500dbfd

The memory flush listeners now also pass metadata (compact_content, which
context injection prefers over content, and enrichment), change_reason and
tags through the secret floor. This applies the same floor once to existing
memories and memory_revisions rows. Like b6850500dbfd: a PostgreSQL regex
preselects, the floor decides, only ids and per-kind counts are logged, the
originals were backed up outside the database, and downgrade restores nothing.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op
from app.services.memory.fingerprint import content_fingerprint
from app.services.secret_redaction import redact_secrets

revision = "d3a9c1f47e20"
down_revision = "b6850500dbfd"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# Same superset of the floor as b6850500dbfd.
CANDIDATE_REGEX = (
    r"(-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36}"
    r"|github_pat_[A-Za-z0-9_]{22}|glpat-[A-Za-z0-9_-]{20}|xox[abposr]-[A-Za-z0-9-]{10}"
    r"|sk-ant-[A-Za-z0-9_-]{20}|[rs]k_live_[A-Za-z0-9]{20})"
)

_TEXT = ("content", "name", "summary", "source_description")
TABLES: dict[str, tuple[str, ...]] = {
    "memories": (*_TEXT, "tags", "metadata"),
    "memory_revisions": (*_TEXT, "change_reason", "tags", "metadata"),
}


def _table(name: str, id_type: Any) -> sa.TableClause:
    columns = [sa.column(column, sa.Text) for column in _TEXT]
    if name == "memories":
        columns.append(sa.column("content_fingerprint", sa.String))
    else:
        columns += [sa.column("change_reason", sa.Text), sa.column("content_hash", sa.String)]
    return sa.table(name, sa.column("id", id_type), sa.column("tags", ARRAY(sa.String)),
                    sa.column("metadata", JSONB), *columns)


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


def redact_rows(bind: sa.Connection) -> tuple[dict[str, list[str]], Counter[str]]:
    """Rewrite every candidate row the floor changes; return ids per table and kind counts."""
    changed: dict[str, list[str]] = {}
    totals: Counter[str] = Counter()
    for name, columns in TABLES.items():
        table = _table(name, UUID(as_uuid=False) if name == "memories" else sa.String)
        as_text = {
            "tags": sa.func.array_to_string(table.c.tags, " "),
            "metadata": sa.cast(table.c.metadata, sa.Text),
        }
        predicate = sa.or_(*(as_text.get(column, table.c[column]).op("~")(CANDIDATE_REGEX) for column in columns))
        rows = bind.execute(
            sa.select(table.c.id, *(table.c[column] for column in columns)).where(predicate).order_by(table.c.id)
        ).all()
        ids: list[str] = []
        for row in rows:
            kinds: Counter[str] = Counter()
            values: dict[str, Any] = {}
            for column in columns:
                before = sum(kinds.values())
                redacted = _redact(getattr(row, column), kinds)
                if sum(kinds.values()) > before:  # untouched columns stay out of the UPDATE
                    values[column] = redacted
            if not values:
                continue
            if "content" in values and name == "memories":
                values["content_fingerprint"] = content_fingerprint(values["content"])
            elif "content" in values:
                values["content_hash"] = hashlib.sha256(values["content"].encode("utf-8")).hexdigest()
            bind.execute(table.update().where(table.c.id == row.id).values(**values))
            ids.append(str(row.id))
            totals.update(kinds)
        changed[name] = ids
    return changed, totals


def upgrade() -> None:
    changed, totals = redact_rows(op.get_bind())
    logger.info(
        "Secret redaction: kinds=%s %s",
        dict(sorted(totals.items())),
        " ".join(f"{name}={len(ids)}:{','.join(ids)}" for name, ids in changed.items()),
    )


def downgrade() -> None:
    # Irreversible by design: restoring would put the credentials back.
    pass
