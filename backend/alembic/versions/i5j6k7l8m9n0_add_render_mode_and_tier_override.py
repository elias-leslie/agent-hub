"""add_render_mode_and_tier_override

Revision ID: i5j6k7l8m9n0
Revises: h4i5j6k7l8m9
Create Date: 2026-05-09 12:00:00.000000

Adds user-controllable render-expansion fields:
- memories.render_mode — per-memory preferred render mode across all profiles
  (full | compact | summary, NULL = auto / use existing tier rules)
- runtime_context_overrides.tier_override — per-profile/per-project tier
  override on a specific memory (L0 | L1 | L2, NULL = no tier override)
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "i5j6k7l8m9n0"
down_revision: str | Sequence[str] | None = "h4i5j6k7l8m9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("render_mode", sa.String(length=16), nullable=True),
    )
    op.create_check_constraint(
        "ck_memories_render_mode",
        "memories",
        "render_mode IS NULL OR render_mode IN ('full', 'compact', 'summary')",
    )

    op.add_column(
        "runtime_context_overrides",
        sa.Column("tier_override", sa.String(length=8), nullable=True),
    )
    op.create_check_constraint(
        "ck_runtime_context_tier_override",
        "runtime_context_overrides",
        "tier_override IS NULL OR tier_override IN ('L0', 'L1', 'L2')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_runtime_context_tier_override",
        "runtime_context_overrides",
        type_="check",
    )
    op.drop_column("runtime_context_overrides", "tier_override")

    op.drop_constraint("ck_memories_render_mode", "memories", type_="check")
    op.drop_column("memories", "render_mode")
