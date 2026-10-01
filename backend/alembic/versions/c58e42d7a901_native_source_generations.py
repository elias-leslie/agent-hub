"""Extend the existing ledger with nullable quarantine subjects and receipt freshness."""

import sqlalchemy as sa

from alembic import op

revision = "c58e42d7a901"
down_revision = "b46d91c2e7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("native_observation_sources", "session_id", existing_type=sa.String(36), nullable=True)
    op.add_column("native_observation_sources", sa.Column("project_id", sa.String(100), nullable=True))
    op.create_index("ix_native_observation_sources_project_id", "native_observation_sources", ["project_id"])
    op.execute("UPDATE native_observation_sources SET project_id = sessions.project_id FROM sessions WHERE native_observation_sources.session_id = sessions.id")
    op.add_column("native_observation_receipts", sa.Column("raw_pruned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("native_observation_receipts", sa.Column("normalized", sa.JSON(), nullable=True))
    op.add_column("native_observation_receipts", sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))

    op.create_table("native_protocol_profiles",
        sa.Column("provider_version", sa.String(256), primary_key=True),
        sa.Column("schema_fingerprint", sa.String(64), nullable=False),
        sa.Column("reference_profile_version", sa.String(256), nullable=False),
        sa.Column("canary_sha256", sa.String(64), nullable=False),
        sa.Column("canary_receipt", sa.JSON(), nullable=False),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table("native_projection_states",
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("acceptance", sa.JSON(), nullable=True),
        sa.Column("next_sequence", sa.Integer(), nullable=False),
    )
    op.create_table("native_user_identities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("namespace", sa.String(512), nullable=False),
        sa.Column("thread_id", sa.String(512), nullable=False),
        sa.Column("turn_id", sa.String(512), nullable=False),
        sa.Column("client_id", sa.String(512), nullable=False),
        sa.Column("durable_item_id", sa.String(512), nullable=True),
        sa.Column("live_verified", sa.Boolean(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("projection_event_ids", sa.JSON(), nullable=False),
    )
    op.create_index("ix_native_user_identities_session_id", "native_user_identities", ["session_id"])


def downgrade() -> None:
    # Refuse to discard durable unbound evidence during a schema downgrade.
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM native_observation_sources WHERE session_id IS NULL) THEN RAISE EXCEPTION 'quarantine evidence prevents native ledger downgrade'; END IF; END $$")
    op.drop_table("native_user_identities")
    op.drop_table("native_projection_states")
    op.drop_table("native_protocol_profiles")
    op.drop_column("native_observation_receipts", "received_at")
    op.drop_column("native_observation_receipts", "normalized")
    op.drop_column("native_observation_receipts", "raw_pruned_at")
    op.drop_index("ix_native_observation_sources_project_id", table_name="native_observation_sources")
    op.drop_column("native_observation_sources", "project_id")
    op.alter_column("native_observation_sources", "session_id", existing_type=sa.String(36), nullable=False)
