"""Context observability: context_deliveries and first-turn columns on usage_sessions.

Revision ID: 3fbbbec251db
Revises: c4e8a1f3d5b7

context_deliveries holds one row per delivery built at a real delivery site (and history imported from the clients'
contract files). usage_sessions gains nullable first-turn columns (harness, version, role, launch mode, model, tokens,
parts, bound delivery, config fingerprint): NULL means not measured. Both are additive; the collector fills them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3fbbbec251db"
down_revision: str | Sequence[str] | None = "c4e8a1f3d5b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USAGE_SESSION_COLUMNS: tuple[sa.Column, ...] = (
    sa.Column("harness", sa.String(20), nullable=True),
    sa.Column("harness_version", sa.String(40), nullable=True),
    sa.Column("work_role", sa.String(50), nullable=True),
    sa.Column("coordinator", sa.Boolean(), nullable=True),
    sa.Column("launch_mode", sa.String(80), nullable=True),
    sa.Column("model", sa.String(100), nullable=True),
    sa.Column("first_turn_tokens", sa.Integer(), nullable=True),
    sa.Column("first_turn_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("parts", postgresql.JSONB(), nullable=True),
    sa.Column("delivery_id", sa.String(64), nullable=True),
    sa.Column("config_fp", sa.String(64), nullable=True),
)


def upgrade() -> None:
    op.create_table(
        "context_deliveries",
        sa.Column("delivery_id", sa.String(64), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("surface", sa.String(100), nullable=False),
        sa.Column("profile", sa.String(100), nullable=True),
        sa.Column("project_id", sa.String(100), nullable=True),
        sa.Column("session_id", sa.String(200), nullable=True),
        sa.Column("agent_slug", sa.String(100), nullable=True),
        sa.Column("work_role", sa.String(50), nullable=True),
        sa.Column("coordinator", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("consumer_tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("provider", sa.String(100), nullable=True),
        sa.Column("host", sa.String(100), nullable=True),
        sa.Column("est_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("rendered_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("by_scope", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("blocks", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_context_deliveries_generated_at", "context_deliveries", ["generated_at"])
    op.create_index("ix_context_deliveries_surface_generated", "context_deliveries", ["surface", "generated_at"])
    op.create_index("ix_context_deliveries_payload_hash", "context_deliveries", ["payload_hash"])
    for column in USAGE_SESSION_COLUMNS:
        op.add_column("usage_sessions", column.copy())
    op.create_index(
        "ix_usage_sessions_harness_first_turn", "usage_sessions", ["harness", "first_turn_at"],
        postgresql_where=sa.text("first_turn_tokens IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_usage_sessions_harness_first_turn", table_name="usage_sessions")
    for column in reversed(USAGE_SESSION_COLUMNS):
        op.drop_column("usage_sessions", column.name)
    op.drop_table("context_deliveries")
