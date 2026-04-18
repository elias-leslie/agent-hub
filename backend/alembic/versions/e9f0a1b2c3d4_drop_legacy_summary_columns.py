"""drop_legacy_summary_columns

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-04-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e9f0a1b2c3d4"
down_revision: str | Sequence[str] | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_SCOPE_FLAG = "summary_is_" + "work" + "tree"


def _drop_column_if_present(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    column_names = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in column_names:
        op.drop_column(table_name, column_name)


def upgrade() -> None:
    """Drop legacy summary scope flags when upgrading existing databases."""
    _drop_column_if_present("sessions", _LEGACY_SCOPE_FLAG)
    _drop_column_if_present("session_summary_segments", _LEGACY_SCOPE_FLAG)


def downgrade() -> None:
    """Recreate legacy summary scope flags for rollback compatibility."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    session_columns = {column["name"] for column in inspector.get_columns("sessions")}
    if _LEGACY_SCOPE_FLAG not in session_columns:
        op.add_column(
            "sessions",
            sa.Column(
                _LEGACY_SCOPE_FLAG,
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    segment_columns = {column["name"] for column in inspector.get_columns("session_summary_segments")}
    if _LEGACY_SCOPE_FLAG not in segment_columns:
        op.add_column(
            "session_summary_segments",
            sa.Column(
                _LEGACY_SCOPE_FLAG,
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
