"""drop unused request_logs indexes and retention prep

Revision ID: 375d38ecdc2e
Revises: 0ff5fb2a634c
Create Date: 2026-03-25 23:11:36.899251

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '375d38ecdc2e'
down_revision: str | Sequence[str] | None = '0ff5fb2a634c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop 3 unused request_logs indexes (~37 MB, 0 scans since stats reset)."""
    op.drop_index("ix_request_logs_client_created", table_name="request_logs")
    op.drop_index("ix_request_logs_client_id", table_name="request_logs")
    op.drop_index("ix_request_logs_tool_name", table_name="request_logs")


def downgrade() -> None:
    """Recreate the dropped indexes."""
    op.create_index(
        "ix_request_logs_client_created",
        "request_logs",
        ["client_id", "created_at"],
    )
    op.create_index(
        "ix_request_logs_client_id",
        "request_logs",
        ["client_id"],
    )
    op.create_index(
        "ix_request_logs_tool_name",
        "request_logs",
        ["tool_name"],
    )
