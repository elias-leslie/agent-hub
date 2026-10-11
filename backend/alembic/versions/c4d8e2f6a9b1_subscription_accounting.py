"""Subscription accounting: plan history, credit lots, usage windows, daily CLI usage, cost_logs split.

Revision ID: c4d8e2f6a9b1
Revises: f3b9d5e7a1c4

Cash is subscription fees + metered API + purchased credits. Calls routed through the Claude and
Codex subscriptions cost $0 marginal; their list-price value is API-equivalent, never spend.

cost_logs gains billing_mode, api_equiv_usd, credits_used and cost_note. Rows on the claude/codex
subscription routes that were recorded at list price (about $1,010 all-time, mostly codex/gpt-5.4 in
March-May and the bare gpt-* names in September) are reclassified, not erased: the original USD moves
to api_equiv_usd, cost_usd becomes 0 and cost_note says so. Downgrade restores cost_usd exactly.

Seeds come from evidence, not assumptions:
- Codex plan periods: plan_type in ~/.codex/sessions token_count rate_limits; each period starts at
  the first record showing the new plan. Plus = $20 and Pro = $200 per the owner; prolite price unverified.
- Claude: Max 20x ($200, owner) since the first ingested Claude session (2026-02-03).
- Codex credit grant: 62,500 credits first reported 2026-09-30T10:29:06Z. One-time grant to Pro 200
  subscribers at DevDay 2026, expiring end of 2026, reference value $2,500 ($0.04/credit):
  https://thenextweb.com/news/openai-devday-pro-200-usage-cut-pro-500-plan
  https://thenewstack.io/openai-halves-200-plan/
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision: str = "c4d8e2f6a9b1"
down_revision: str | Sequence[str] | None = "f3b9d5e7a1c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RECLASS_NOTE = "reclassified 2026-10-11: subscription route recorded at list price; original USD in api_equiv_usd"
SUBSCRIPTION_PROVIDERS = "('claude', 'codex')"

_CODEX_EVIDENCE = "plan_type in ~/.codex/sessions rate_limits; first record on this plan"
_PLANS = [
    ("codex", "pro", 200.0, True, "2026-05-05T19:09:57Z", "2026-05-07T14:09:01Z", _CODEX_EVIDENCE),
    ("codex", "prolite", None, False, "2026-05-07T14:09:01Z", "2026-08-31T14:20:25Z",
     _CODEX_EVIDENCE + "; price unverified; no Codex logs June-August"),
    ("codex", "plus", 20.0, True, "2026-08-31T14:20:25Z", "2026-09-07T15:05:04Z", _CODEX_EVIDENCE),
    ("codex", "prolite", None, False, "2026-09-07T15:05:04Z", "2026-09-09T16:08:41Z",
     _CODEX_EVIDENCE + "; price unverified"),
    ("codex", "pro", 200.0, True, "2026-09-09T16:08:41Z", "2026-10-10T14:05:10Z", _CODEX_EVIDENCE),
    ("codex", "plus", 20.0, True, "2026-10-10T14:05:10Z", None, _CODEX_EVIDENCE + "; owner confirmed $20/month"),
    ("claude", "max_20x", 200.0, True, "2026-02-03T00:00:00Z", None,
     "rateLimitTier default_claude_max_20x in ~/.claude.json; owner confirmed $200/month; "
     "start = first ingested Claude session"),
]

# Codex credits per 1M tokens (input, cached, output) x $0.04/credit = API list price.
# learn.chatgpt.com/docs/pricing.md. Used to backfill API-equivalent on $0 Codex rows.
_CODEX_RATES = {
    "gpt-6.1-sol": (50.0, 2.5, 250.0),
    "gpt-6-sol": (50.0, 5.0, 250.0),
    "gpt-6-luna": (2.5, 0.25, 12.5),
    "gpt-6-astra": (250.0, 25.0, 1250.0),
    "gpt-daybreak-blue-latest": (100.0, 10.0, 500.0),
    "gpt-5.6-sol": (100.0, 10.0, 500.0),
}


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def upgrade() -> None:
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("plan", sa.String(64), nullable=False),
        sa.Column("monthly_usd", sa.Float(), nullable=True),
        sa.Column("price_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_subscription_plans_provider_from", "subscription_plans", ["provider", "effective_from"])

    op.create_table(
        "credit_lots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("credits", sa.Float(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("value_usd_per_credit", sa.Float(), nullable=True),
        sa.Column("paid_usd", sa.Float(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "subscription_usage_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_minutes", sa.Integer(), nullable=False),
        sa.Column("used_percent", sa.Float(), nullable=False),
        sa.Column("resets_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_type", sa.String(64), nullable=True),
        sa.Column("credits_balance", sa.Float(), nullable=True),
        sa.UniqueConstraint("provider", "window_minutes", "observed_at", name="uq_subscription_usage_snapshot"),
    )
    op.create_index(
        "ix_subscription_usage_snapshots_provider_observed", "subscription_usage_snapshots", ["provider", "observed_at"]
    )

    op.create_table(
        "subscription_usage_daily",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column("model", sa.String(100), primary_key=True),
        sa.Column("project", sa.String(200), primary_key=True),
        sa.Column("speed", sa.String(16), primary_key=True),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cached_input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("api_equiv_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unpriced_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("credits_drawn", sa.Float(), nullable=False, server_default="0"),
    )

    op.create_table(
        "subscription_usage_cursors",
        sa.Column("path", sa.Text(), primary_key=True),
        sa.Column("offset", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("state", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.add_column("cost_logs", sa.Column("billing_mode", sa.String(16), nullable=False, server_default="metered"))
    op.add_column("cost_logs", sa.Column("api_equiv_usd", sa.Float(), nullable=True))
    op.add_column("cost_logs", sa.Column("credits_used", sa.Float(), nullable=True))
    op.add_column("cost_logs", sa.Column("cost_note", sa.String(200), nullable=True))

    plans = sa.table(
        "subscription_plans",
        sa.column("provider", sa.String), sa.column("plan", sa.String), sa.column("monthly_usd", sa.Float),
        sa.column("price_verified", sa.Boolean), sa.column("effective_from", sa.DateTime(timezone=True)),
        sa.column("effective_to", sa.DateTime(timezone=True)), sa.column("evidence", sa.Text),
    )
    op.bulk_insert(plans, [
        {"provider": p, "plan": n, "monthly_usd": usd, "price_verified": ok, "effective_from": _ts(f),
         "effective_to": _ts(t), "evidence": e}
        for p, n, usd, ok, f, t, e in _PLANS
    ])
    lots = sa.table(
        "credit_lots",
        sa.column("provider", sa.String), sa.column("source", sa.String), sa.column("credits", sa.Float),
        sa.column("granted_at", sa.DateTime(timezone=True)), sa.column("expires_at", sa.DateTime(timezone=True)),
        sa.column("value_usd_per_credit", sa.Float), sa.column("paid_usd", sa.Float), sa.column("evidence", sa.Text),
    )
    op.bulk_insert(lots, [{
        "provider": "codex", "source": "grant", "credits": 62500.0,
        "granted_at": _ts("2026-09-30T10:29:06Z"), "expires_at": _ts("2026-12-31T23:59:59Z"),
        "value_usd_per_credit": 0.04, "paid_usd": None,
        "evidence": (
            "One-time grant to Pro 200 subscribers at DevDay 2026, 'worth $2,500', expires end of 2026; "
            "first balance report 2026-09-30T10:29:06Z. "
            "https://thenextweb.com/news/openai-devday-pro-200-usage-cut-pro-500-plan "
            "https://thenewstack.io/openai-halves-200-plan/"
        ),
    }])

    # Subscription-route rows: mark them, then move list-price USD out of cash.
    op.execute(
        f"""
        UPDATE cost_logs c SET billing_mode = 'subscription'
        FROM sessions s
        WHERE s.id = c.session_id AND s.provider IN {SUBSCRIPTION_PROVIDERS}
        """
    )
    op.execute(
        f"""
        UPDATE cost_logs SET api_equiv_usd = cost_usd, cost_usd = 0, cost_note = '{RECLASS_NOTE}'
        WHERE billing_mode = 'subscription' AND cost_usd > 0
        """
    )
    # Backfill API-equivalent for $0 Codex rows whose model has a published rate.
    for model, (inp, cached, out) in _CODEX_RATES.items():
        op.execute(
            sa.text(
                """
                UPDATE cost_logs SET api_equiv_usd =
                  (input_tokens * :inp + cache_read_tokens * :cached + output_tokens * :out) / 1e6 * 0.04
                WHERE billing_mode = 'subscription' AND api_equiv_usd IS NULL
                  AND (model = :m OR model = :pm)
                """
            ).bindparams(inp=inp, cached=cached, out=out, m=model, pm=f"codex/{model}")
        )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE cost_logs SET cost_usd = api_equiv_usd
        WHERE cost_note = '{RECLASS_NOTE}'
        """
    )
    op.drop_column("cost_logs", "cost_note")
    op.drop_column("cost_logs", "credits_used")
    op.drop_column("cost_logs", "api_equiv_usd")
    op.drop_column("cost_logs", "billing_mode")
    op.drop_table("subscription_usage_cursors")
    op.drop_table("subscription_usage_daily")
    op.drop_index("ix_subscription_usage_snapshots_provider_observed", table_name="subscription_usage_snapshots")
    op.drop_table("subscription_usage_snapshots")
    op.drop_table("credit_lots")
    op.drop_index("ix_subscription_plans_provider_from", table_name="subscription_plans")
    op.drop_table("subscription_plans")
