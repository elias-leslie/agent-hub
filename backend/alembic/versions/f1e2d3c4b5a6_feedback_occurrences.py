"""Retain sessionless feedback occurrences without creating work.

Revision ID: f1e2d3c4b5a6
Revises: c58e42d7a901
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f1e2d3c4b5a6"
down_revision = "c58e42d7a901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Native reporters and retained initial reports need no managed session.
    op.alter_column("feedback_votes", "session_id", nullable=True)
    for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys("feedback_votes"):
        if foreign_key["constrained_columns"] == ["session_id"]:
            name = foreign_key["name"]
            assert name is not None
            op.drop_constraint(name, "feedback_votes", type_="foreignkey")
    op.create_foreign_key("fk_feedback_votes_session", "feedback_votes", "sessions",
                          ["session_id"], ["id"], ondelete="SET NULL")
    for column in (
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("independent_run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("affected_roles", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("affected_projects", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("merged_into_id", postgresql.UUID(as_uuid=False), nullable=True),
    ):
        op.add_column("feedback_items", column)
    op.create_foreign_key("fk_feedback_items_merged_into", "feedback_items", "feedback_items",
                          ["merged_into_id"], ["id"], ondelete="CASCADE")
    for column in (
        sa.Column("occurrence_id", sa.String(160), nullable=True),
        sa.Column("source_project_id", sa.String(50), nullable=True),
        sa.Column("run_ref", sa.String(200), nullable=True),
        sa.Column("role", sa.String(100), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consequence", sa.Text(), nullable=True),
        sa.Column("workaround", sa.Text(), nullable=True),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("source_kind", sa.String(30), nullable=False, server_default="report"),
    ):
        op.add_column("feedback_votes", column)
    # Old rows establish a submitted vote, not its run, role, source project or evidence.
    op.execute("""
        UPDATE feedback_votes SET occurrence_id = 'legacy-vote:' || id::text,
            occurred_at = created_at, source_kind = 'legacy_vote'
    """)
    op.execute("""
        INSERT INTO feedback_votes
            (feedback_item_id, session_id, occurrence_id, source_project_id,
             comment, agent_slug, model_used, created_at, occurred_at, source_kind)
        SELECT fi.id, fi.created_by_session_id, 'legacy-item:' || fi.id::text,
               fi.project_id, fi.description, fi.agent_slug, fi.model_used,
               fi.created_at, fi.created_at, 'legacy_report'
        FROM feedback_items fi
        WHERE NOT EXISTS (SELECT 1 FROM feedback_votes fv
            WHERE fv.feedback_item_id = fi.id AND fi.created_by_session_id IS NOT NULL
              AND fv.session_id = fi.created_by_session_id)
    """)
    op.execute("""
        UPDATE feedback_items fi SET vote_count = aggregate.n,
            last_seen_at = aggregate.last_seen,
            affected_projects = jsonb_build_array(fi.project_id)
        FROM (SELECT feedback_item_id, COUNT(*) AS n, MAX(occurred_at) AS last_seen
              FROM feedback_votes GROUP BY feedback_item_id) aggregate
        WHERE fi.id = aggregate.feedback_item_id;
    """)
    op.alter_column("feedback_votes", "occurrence_id", nullable=False)
    op.alter_column("feedback_votes", "occurred_at", nullable=False, server_default=sa.func.now())
    op.drop_constraint("uq_feedback_votes_item_session", "feedback_votes", type_="unique")
    op.create_unique_constraint("uq_feedback_votes_occurrence", "feedback_votes", ["occurrence_id"])
    op.create_index("idx_feedback_votes_source_project", "feedback_votes", ["source_project_id", "feedback_item_id"])
    op.create_index("idx_feedback_items_last_seen", "feedback_items", ["last_seen_at"])


def downgrade() -> None:
    # Never silently discard independent observations to satisfy the old constraint.
    sessionless = op.get_bind().execute(sa.text("SELECT 1 FROM feedback_votes WHERE session_id IS NULL LIMIT 1")).first()
    if sessionless:
        raise RuntimeError("Cannot downgrade feedback: sessionless occurrences require the current schema")
    duplicates = op.get_bind().execute(sa.text("""
        SELECT 1 FROM feedback_votes WHERE session_id IS NOT NULL
        GROUP BY feedback_item_id, session_id HAVING COUNT(*) > 1 LIMIT 1
    """)).first()
    if duplicates:
        raise RuntimeError("Cannot downgrade feedback: independent occurrences share a session")
    op.drop_index("idx_feedback_items_last_seen", table_name="feedback_items")
    op.drop_index("idx_feedback_votes_source_project", table_name="feedback_votes")
    op.drop_constraint("uq_feedback_votes_occurrence", "feedback_votes", type_="unique")
    op.create_unique_constraint("uq_feedback_votes_item_session", "feedback_votes", ["feedback_item_id", "session_id"])
    for name in ("occurrence_id", "source_project_id", "run_ref", "role", "occurred_at",
                 "consequence", "workaround", "evidence_refs", "source_kind"):
        op.drop_column("feedback_votes", name)
    op.drop_constraint("fk_feedback_items_merged_into", "feedback_items", type_="foreignkey")
    for name in ("last_seen_at", "independent_run_count", "affected_roles", "affected_projects", "merged_into_id"):
        op.drop_column("feedback_items", name)
