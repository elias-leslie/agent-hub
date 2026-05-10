"""add_runtime_context_profile_policies

Revision ID: l8m9n0o1p2q3
Revises: k7l8m9n0o1p2
Create Date: 2026-05-10 00:00:00.000000

Persists per-profile mandate/guardrail/reference caps that previously lived in
a hard-coded Python dict (services.memory.context_profiles._PROFILE_POLICY_LIMITS).
NULL caps mean uncapped; integers cap inclusively. Existing values are seeded
so deploy is behaviourally inert.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "l8m9n0o1p2q3"
down_revision: str | Sequence[str] | None = "k7l8m9n0o1p2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_context_profile_policies",
        sa.Column("consumer_profile", sa.String(length=64), primary_key=True),
        sa.Column("mandate_limit", sa.Integer(), nullable=True),
        sa.Column("guardrail_limit", sa.Integer(), nullable=True),
        sa.Column("reference_limit", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute(
        """
        INSERT INTO runtime_context_profile_policies
            (consumer_profile, mandate_limit, guardrail_limit, reference_limit)
        VALUES
            ('agent_preview', 8, 2, NULL),
            ('agent_general', 6, 2, NULL),
            ('agent_visual', 6, 2, NULL),
            ('agent_coding', 16, 4, NULL),
            ('agent_operator', 20, 6, NULL),
            ('agent_promptops', 14, 4, NULL),
            ('agent_startup', 28, 6, NULL)
        """
    )


def downgrade() -> None:
    op.drop_table("runtime_context_profile_policies")
