"""add typesafe jev pilot ledger

Revision ID: be3b1a9a2e21
Revises: 6f708192a3b4
Create Date: 2026-09-19 10:56:56.029415

"""

from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "be3b1a9a2e21"
down_revision: str | Sequence[str] | None = "6f708192a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    budgets = op.create_table(
        "typesafe_jev_budgets",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("ceiling_usd", sa.Numeric(12, 9), nullable=False),
        sa.Column("spent_usd", sa.Numeric(12, 9), nullable=False, server_default="0"),
        sa.Column("reserved_usd", sa.Numeric(12, 9), nullable=False, server_default="0"),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("pricing_contract", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "typesafe_jev_dispatches",
        sa.Column("request_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "budget_key",
            sa.String(length=100),
            sa.ForeignKey("typesafe_jev_budgets.key"),
            nullable=False,
        ),
        sa.Column("request_sha256", sa.String(length=64), nullable=False, unique=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("model_requested", sa.String(length=100), nullable=False),
        sa.Column("model_observed", sa.String(length=100), nullable=True),
        sa.Column("pricing_contract", sa.String(length=200), nullable=False),
        sa.Column("reserved_input_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_cost_usd", sa.Numeric(12, 9), nullable=False),
        sa.Column("actual_input_tokens", sa.Integer(), nullable=True),
        sa.Column("actual_output_tokens", sa.Integer(), nullable=True),
        sa.Column("actual_cost_usd", sa.Numeric(12, 9), nullable=True),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("source_provenance", sa.JSON(), nullable=False),
        sa.Column("rubric_provenance", sa.JSON(), nullable=False),
        sa.Column("observation_provenance", sa.JSON(), nullable=True),
        sa.Column("answers", sa.JSON(), nullable=True),
        sa.Column("error_kind", sa.String(length=80), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_typesafe_jev_dispatches_budget_key",
        "typesafe_jev_dispatches",
        ["budget_key"],
    )
    op.create_index(
        "ix_typesafe_jev_dispatches_budget_status",
        "typesafe_jev_dispatches",
        ["budget_key", "status"],
    )
    op.bulk_insert(
        budgets,
        [
            {
                "key": "-".join(("neri", "jev", "pilot", "2026", "09")),
                "ceiling_usd": Decimal("5.000000000"),
                "spent_usd": Decimal("0.000000000"),
                "reserved_usd": Decimal("0.000000000"),
                "model_id": "jev-1.13.0",
                "pricing_contract": "jev-1.13.0:usd-0.042-per-million-input:2026-09-19",
            }
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_typesafe_jev_dispatches_budget_status",
        table_name="typesafe_jev_dispatches",
    )
    op.drop_index(
        "ix_typesafe_jev_dispatches_budget_key",
        table_name="typesafe_jev_dispatches",
    )
    op.drop_table("typesafe_jev_dispatches")
    op.drop_table("typesafe_jev_budgets")
