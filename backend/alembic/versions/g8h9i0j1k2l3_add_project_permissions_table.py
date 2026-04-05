"""add_project_permissions_table

Revision ID: g8h9i0j1k2l3
Revises: f7g8h9i0j1k2
Create Date: 2026-02-23 12:00:00.000000

Adds:
1. project_permissions table for centralized automation access control
2. Seeds rows for all VALID_PROJECT_IDS with default tier="read"
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "g8h9i0j1k2l3"
down_revision: str | Sequence[str] | None = "f7g8h9i0j1k2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(conn: sa.Connection, table: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :name)"
        ),
        {"name": table},
    )
    return result.scalar() or False


# Known project root paths (real projects only; utility scopes have no root)
_PROJECT_SEEDS = [
    # (project_id, tier, auto_exec, start_hour, end_hour, root_path)
    ("summitflow", "read", False, 0, 24, "$HOME/summitflow"),
    ("agent-hub", "read", False, 0, 24, "$HOME/agent-hub"),
    ("portfolio-ai", "read", False, 0, 24, "$HOME/portfolio-ai"),
    ("aterm", "read", False, 0, 24, "$HOME/aterm"),
    ("monkey-fight", "read", False, 0, 24, "$HOME/monkey-fight"),
    # Utility scopes — no root_path
    ("st-cli", "read", False, 0, 24, None),
    ("claude-consultation", "read", False, 0, 24, None),
    ("consult", "read", False, 0, 24, None),
    ("agent-playground", "read", False, 0, 24, None),
]


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "project_permissions"):
        op.create_table(
            "project_permissions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("project_id", sa.String(100), nullable=False, unique=True),
            sa.Column("permission_tier", sa.String(10), nullable=False, server_default="read"),
            sa.Column("auto_exec_enabled", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("execution_start_hour", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("execution_end_hour", sa.Integer(), nullable=False, server_default="24"),
            sa.Column("root_path", sa.String(500), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_project_permissions_project_id",
            "project_permissions",
            ["project_id"],
            unique=True,
        )

    # Seed rows for all known projects (skip if already present)
    for project_id, tier, auto_exec, start_h, end_h, root_path in _PROJECT_SEEDS:
        exists = conn.execute(
            sa.text("SELECT 1 FROM project_permissions WHERE project_id = :pid"),
            {"pid": project_id},
        ).scalar()
        if not exists:
            conn.execute(
                sa.text(
                    "INSERT INTO project_permissions "
                    "(project_id, permission_tier, auto_exec_enabled, "
                    "execution_start_hour, execution_end_hour, root_path) "
                    "VALUES (:pid, :tier, :auto_exec, :start_h, :end_h, :root_path)"
                ),
                {
                    "pid": project_id,
                    "tier": tier,
                    "auto_exec": auto_exec,
                    "start_h": start_h,
                    "end_h": end_h,
                    "root_path": root_path,
                },
            )


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "project_permissions"):
        op.drop_index("ix_project_permissions_project_id", table_name="project_permissions")
        op.drop_table("project_permissions")
