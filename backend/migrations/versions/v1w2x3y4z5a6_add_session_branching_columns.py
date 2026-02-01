"""add_session_branching_columns

Revision ID: v1w2x3y4z5a6
Revises: u0v1w2x3y4z5
Create Date: 2026-02-01 15:00:00.000000

Adds session branching support for A/B testing, exploration, and 3-2-1 escalation:
- parent_session_id: FK to parent session for forked branches
- fork_point_turn: Turn number where the fork occurred
- pending_patches: JSON for uncommitted file changes (Mutex pattern)
- branch_status: active/promoted/discarded
- continuation_count: Turns since fork
- manual_outcome: User-set outcome (selected/discarded)
- task_outcome: SummitFlow verification outcome (passed/failed)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v1w2x3y4z5a6"
down_revision: str | Sequence[str] | None = "u0v1w2x3y4z5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add session branching columns."""
    # Create enums first
    branch_status_enum = sa.Enum("active", "promoted", "discarded", name="branch_status_enum")
    manual_outcome_enum = sa.Enum("selected", "discarded", name="manual_outcome_enum")
    task_outcome_enum = sa.Enum("passed", "failed", name="task_outcome_enum")

    branch_status_enum.create(op.get_bind(), checkfirst=True)
    manual_outcome_enum.create(op.get_bind(), checkfirst=True)
    task_outcome_enum.create(op.get_bind(), checkfirst=True)

    # Add columns
    op.add_column(
        "sessions",
        sa.Column("parent_session_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("fork_point_turn", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("pending_patches", sa.JSON(), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "branch_status",
            branch_status_enum,
            nullable=True,
        ),
    )
    op.add_column(
        "sessions",
        sa.Column("continuation_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "manual_outcome",
            manual_outcome_enum,
            nullable=True,
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "task_outcome",
            task_outcome_enum,
            nullable=True,
        ),
    )

    # Add foreign key constraint
    op.create_foreign_key(
        "fk_sessions_parent_session",
        "sessions",
        "sessions",
        ["parent_session_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Add index for parent session lookups
    op.create_index("ix_sessions_parent", "sessions", ["parent_session_id"])


def downgrade() -> None:
    """Remove session branching columns."""
    op.drop_index("ix_sessions_parent", table_name="sessions")
    op.drop_constraint("fk_sessions_parent_session", "sessions", type_="foreignkey")
    op.drop_column("sessions", "task_outcome")
    op.drop_column("sessions", "manual_outcome")
    op.drop_column("sessions", "continuation_count")
    op.drop_column("sessions", "branch_status")
    op.drop_column("sessions", "pending_patches")
    op.drop_column("sessions", "fork_point_turn")
    op.drop_column("sessions", "parent_session_id")

    # Drop enums
    sa.Enum(name="task_outcome_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="manual_outcome_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="branch_status_enum").drop(op.get_bind(), checkfirst=True)
