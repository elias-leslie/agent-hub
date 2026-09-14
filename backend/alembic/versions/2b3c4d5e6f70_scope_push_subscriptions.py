"""Add explicit push application ownership; preserve unknown legacy rows."""

import sqlalchemy as sa

from alembic import op

revision = "2b3c4d5e6f70"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("push_subscriptions", sa.Column("application_id", sa.String(100), nullable=True))
    op.add_column("push_subscriptions", sa.Column("owner_id", sa.String(100), nullable=True))
    op.create_index("ix_push_subscriptions_application_owner", "push_subscriptions", ["application_id", "owner_id"])
    # Existing NULL-scoped endpoints are not assigned to an application by guess.
    # Explicit registration with the same endpoint keys may bind one later.


def downgrade() -> None:
    # Removing scope could turn surviving subscriptions into broadcast recipients.
    # Keep the additive columns/data across a code rollback.
    raise RuntimeError("Push ownership cannot be downgraded to unscoped broadcast delivery.")
