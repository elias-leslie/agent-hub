"""drop_adaptive_routing_tables

Revision ID: p2q3r4s5t6u7
Revises: o1p2q3r4s5t6
Create Date: 2026-05-13 09:20:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "p2q3r4s5t6u7"
down_revision = "o1p2q3r4s5t6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("model_workload_performance", if_exists=True)
    op.drop_table("routing_decisions", if_exists=True)
    op.drop_table("routing_policy_versions", if_exists=True)
    op.drop_table("model_capability_scores", if_exists=True)
    op.drop_table("model_availability", if_exists=True)
    op.drop_table("provider_entitlements", if_exists=True)
    op.drop_table("manual_model_routes", if_exists=True)
    op.drop_table("agent_workload_routing_modes", if_exists=True)
    op.drop_table("agent_routing_profiles", if_exists=True)
    op.drop_table("workload_profiles", if_exists=True)
    op.drop_table("capability_dimensions", if_exists=True)


def downgrade() -> None:
    # Deliberately not recreated: these tables backed the removed adaptive router.
    pass
