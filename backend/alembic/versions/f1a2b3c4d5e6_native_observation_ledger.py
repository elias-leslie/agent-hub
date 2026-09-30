"""Add the versioned native source ledger and shadow command reconciliation."""

import sqlalchemy as sa

from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("native_observation_sources",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("registration", sa.JSON(), nullable=False),
        sa.Column("authenticity", sa.String(32), nullable=False),
        sa.Column("committed_position", sa.Integer(), nullable=False),
    )
    op.create_index("ix_native_observation_sources_session_id", "native_observation_sources", ["session_id"])
    op.create_table("native_command_entities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("namespace", sa.String(512), nullable=False),
        sa.Column("thread_id", sa.String(512), nullable=False),
        sa.Column("turn_id", sa.String(512), nullable=False),
        sa.Column("item_id", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("command", sa.JSON(), nullable=False),
        sa.Column("projection_event_ids", sa.JSON(), nullable=False),
        sa.Column("observed_model", sa.String(512), nullable=True),
    )
    op.create_index("ix_native_command_entities_session_id", "native_command_entities", ["session_id"])
    op.create_table("native_observation_receipts",
        sa.Column("source_id", sa.String(64), sa.ForeignKey("native_observation_sources.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("position", sa.Integer(), primary_key=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("observation", sa.JSON(), nullable=False),
        sa.Column("disposition", sa.String(32), nullable=False),
        sa.Column("issue_code", sa.String(100), nullable=True),
        sa.Column("entity_id", sa.String(64), sa.ForeignKey("native_command_entities.id"), nullable=True),
    )
    op.create_index("ix_native_observation_receipts_entity_id", "native_observation_receipts", ["entity_id"])
    op.create_table("native_observation_issues",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("native_observation_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("observation", sa.JSON(), nullable=False),
    )
    op.create_index("ix_native_observation_issues_source_id", "native_observation_issues", ["source_id"])


def downgrade() -> None:
    op.drop_table("native_observation_issues")
    op.drop_table("native_observation_receipts")
    op.drop_table("native_command_entities")
    op.drop_table("native_observation_sources")
