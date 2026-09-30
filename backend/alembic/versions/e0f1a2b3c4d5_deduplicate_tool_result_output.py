"""Store identical tool-result output once in canonical content.

The full original text remains searchable in content. The owning model accessor
reconstructs output; an explicit flag preserves metadata-only payloads. Only exact
string equality qualifies, and downgrade reverses the representation change.
"""

import logging

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def _events() -> sa.TableClause:
    return sa.table(
        "session_events",
        sa.column("event_type", sa.String),
        sa.column("content", sa.Text),
        sa.column("tool_output", JSONB),
        sa.column("tool_output_from_content", sa.Boolean),
    )


def _duplicate_predicate(events):
    return sa.and_(
        events.c.event_type == "tool_result",
        events.c.tool_output_from_content.is_(False),
        events.c.content.is_not(None),
        sa.func.jsonb_typeof(events.c.tool_output) == "object",
        sa.func.jsonb_typeof(events.c.tool_output["output"]) == "string",
        events.c.content == events.c.tool_output["output"].astext,
    )


def upgrade() -> None:
    op.add_column(
        "session_events",
        sa.Column("tool_output_from_content", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    events = _events()
    bind = op.get_bind()
    rows, text_bytes = bind.execute(
        sa.select(sa.func.count(), sa.func.coalesce(sa.func.sum(sa.func.octet_length(events.c.content)), 0))
        .where(_duplicate_predicate(events))
    ).one()
    result = bind.execute(
        events.update().where(_duplicate_predicate(events)).values(
            tool_output=events.c.tool_output.op("-")("output"),
            tool_output_from_content=True,
        )
    )
    logger.info(
        "Tool-output deduplication: eligible_rows=%s updated_rows=%s duplicate_text_bytes=%s; canonical content retained",
        rows, result.rowcount, text_bytes,
    )


def downgrade() -> None:
    events = _events()
    bind = op.get_bind()
    # Fail closed if canonical text or metadata changed outside the model contract.
    invalid = bind.execute(
        sa.select(sa.func.count()).where(
            events.c.tool_output_from_content.is_(True),
            sa.or_(
                events.c.content.is_(None),
                events.c.tool_output.is_(None),
                sa.func.jsonb_typeof(events.c.tool_output) != "object",
                events.c.tool_output.has_key("output"),
            ),
        )
    ).scalar_one()
    if invalid:
        raise RuntimeError("Cannot restore tool output: compacted records have invalid canonical content or metadata")
    result = bind.execute(
        events.update().where(events.c.tool_output_from_content.is_(True)).values(
            tool_output=events.c.tool_output.op("||")(sa.func.jsonb_build_object("output", events.c.content)),
            tool_output_from_content=False,
        )
    )
    logger.info("Tool-output deduplication reversed: restored_rows=%s", result.rowcount)
    op.drop_column("session_events", "tool_output_from_content")
