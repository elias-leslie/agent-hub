"""Canonical automation definitions, policies, profiles, and durable runs.

Revision ID: 5c6b7a8d9e0f
Revises: e9b41fc275c3
"""

import sqlalchemy as sa

from alembic import op

revision = "5c6b7a8d9e0f"
down_revision = "e9b41fc275c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("automation_definitions",
        sa.Column("workflow_key", sa.String(160), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("owner_project_id", sa.String(100), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("dispatch_kind", sa.String(30), nullable=False),
        sa.Column("dispatch_target", sa.String(300), nullable=False),
        sa.Column("credential_ref", sa.String(200)),
        sa.Column("config_schema", sa.JSON(), nullable=False),
        sa.Column("policy_schema", sa.JSON(), nullable=False),
        sa.Column("default_schedule", sa.JSON(), nullable=False),
        sa.Column("default_enabled", sa.Boolean(), nullable=False),
        sa.Column("manual_when_disabled", sa.Boolean(), nullable=False),
        sa.Column("manual_advances_cursor", sa.Boolean(), nullable=False),
        sa.Column("overlap_strategy", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("automation_project_policies",
        sa.Column("project_id", sa.String(100), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("sync_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_by", sa.String(160)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table("automation_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("subject_id", sa.String(160)),
        sa.Column("workflow_key", sa.String(160), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("schedule_type", sa.String(20), nullable=False),
        sa.Column("schedule_value", sa.String(160), nullable=False),
        sa.Column("schedule_timezone", sa.String(64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("clock_owner", sa.String(20), nullable=False),
        sa.Column("owner_gate_reasons", sa.JSON(), nullable=False),
        sa.Column("source_ref", sa.String(200), unique=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("max_runs", sa.Integer()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("imported_unreviewed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_automation_profiles_due", "automation_profiles", ["clock_owner", "enabled", "next_run_at"])
    op.create_index("ix_automation_profiles_project", "automation_profiles", ["project_id", "subject_id"])
    op.create_table("automation_profile_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("automation_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("changed_by", sa.String(160)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("profile_id", "revision", name="uq_automation_profile_revisions_profile_id"))
    op.create_table("automation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("automation_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_id", sa.String(100), nullable=False),
        sa.Column("workflow_key", sa.String(160), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("occurrence_key", sa.String(200), nullable=False, unique=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("gate_reasons", sa.JSON(), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("owner_run_id", sa.String(200)),
        sa.Column("owner_receipt", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("requested_by", sa.String(160)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_automation_runs_profile_created", "automation_runs", ["profile_id", "created_at"])


def downgrade() -> None:
    op.drop_table("automation_runs")
    op.drop_table("automation_profile_revisions")
    op.drop_table("automation_profiles")
    op.drop_table("automation_project_policies")
    op.drop_table("automation_definitions")
