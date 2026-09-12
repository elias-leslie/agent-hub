"""Add durable receipts for retained Codex native-thread turns."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "1a2b3c4d5e6f"
down_revision = "0c78d126e3ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "native_continuation_turns",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("expected_turn", sa.Integer(), nullable=False),
        sa.Column("accepted_turn", sa.Integer(), nullable=False),
        sa.Column("context_version", sa.String(length=100), nullable=False),
        sa.Column("instruction_hash", sa.String(length=64), nullable=False),
        sa.Column("tool_policy_hash", sa.String(length=64), nullable=False),
        sa.Column("runtime_status", sa.String(length=20), nullable=False),
        sa.Column("agent_used", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("native_thread_id", sa.String(length=100), nullable=True),
        sa.Column("native_turn_id", sa.String(length=100), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("model_used", sa.String(length=100), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reasoning_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("usage_known", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "generation",
            "request_id",
            name="uq_native_continuation_turn_request",
        ),
    )
    op.create_index(
        "ix_native_continuation_turn_session_generation",
        "native_continuation_turns",
        ["session_id", "generation", "accepted_turn"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_native_continuation_turn_session_generation",
        table_name="native_continuation_turns",
    )
    op.drop_table("native_continuation_turns")
