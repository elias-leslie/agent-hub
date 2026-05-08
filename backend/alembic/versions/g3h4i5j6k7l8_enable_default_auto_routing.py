"""enable_default_auto_routing

Revision ID: g3h4i5j6k7l8
Revises: f2a3b4c5d6e7
Create Date: 2026-05-08 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "g3h4i5j6k7l8"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: str | None = None
depends_on: str | None = None

PROTECTED_AGENT_SLUGS = (
    "persona",
    "verifier",
    "equity-analyst",
    "financial-document-reviewer",
    "governance-auditor",
    "investment-committee",
    "market-pulse-analyst",
    "market-pulse-scout",
    "risk-manager",
    "trade-manager",
)

AUTO_WORKLOADS = (
    "general",
    "planning",
    "coding_impl",
    "code_review",
    "data_analysis",
    "deep_research",
    "prompt_building",
    "summarization",
    "memory_curation",
    "ui_design",
    "vision_qa",
    "voice_response",
)

LOCKED_WORKLOADS = (
    "jenny_planning",
    "verifier",
    "finance_research",
    "trade_strategy",
    "market_scan",
    "image_generation",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.alter_column(
        "workload_profiles",
        "default_routing_mode",
        server_default=sa.text("'auto'"),
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.alter_column(
        "agent_routing_profiles",
        "default_routing_mode",
        server_default=sa.text("'auto'"),
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.execute(
        """
        INSERT INTO workload_profiles
            (key, label, requirement_deltas, hard_constraints, risk_tier, verifier_policy, default_routing_mode)
        VALUES
            (
                'planning',
                'Planning/Orchestration',
                '{"planning_orchestration": 1.0, "reasoning": 0.7, "instruction": 0.5}'::jsonb,
                '{}'::jsonb,
                'normal',
                'optional',
                'auto'
            )
        ON CONFLICT (key) DO UPDATE
        SET
            label = EXCLUDED.label,
            requirement_deltas = EXCLUDED.requirement_deltas,
            hard_constraints = EXCLUDED.hard_constraints,
            risk_tier = EXCLUDED.risk_tier,
            verifier_policy = EXCLUDED.verifier_policy,
            default_routing_mode = EXCLUDED.default_routing_mode
        """
    )
    op.execute(
        f"""
        UPDATE workload_profiles
        SET default_routing_mode = 'auto'
        WHERE key IN ({_quoted(AUTO_WORKLOADS)})
        """
    )
    op.execute(
        f"""
        UPDATE workload_profiles
        SET default_routing_mode = 'manual_locked'
        WHERE key IN ({_quoted(LOCKED_WORKLOADS)})
        """
    )
    op.execute(
        f"""
        UPDATE agent_routing_profiles
        SET
            default_routing_mode = 'manual_locked',
            risk_tier = 'critical',
            exploration_policy = 'disabled',
            metadata = jsonb_set(COALESCE(metadata, '{{}}'::jsonb), '{{source}}', '"auto-routing-enable-v1"'::jsonb, true)
        WHERE agent_slug IN ({_quoted(PROTECTED_AGENT_SLUGS)})
        """
    )
    op.execute(
        f"""
        UPDATE agent_routing_profiles
        SET
            default_routing_mode = 'auto',
            risk_tier = 'normal',
            exploration_policy = 'auto',
            metadata = jsonb_set(COALESCE(metadata, '{{}}'::jsonb), '{{source}}', '"auto-routing-enable-v1"'::jsonb, true)
        WHERE agent_slug NOT IN ({_quoted(PROTECTED_AGENT_SLUGS)})
          AND (
            default_routing_mode = 'auto_shadow'
            OR COALESCE(metadata ->> 'source', '') IN ('migration', 'startup_seed', 'auto-routing-enable-v1')
          )
        """
    )
    op.execute(
        """
        UPDATE provider_entitlements
        SET metadata = COALESCE(metadata, '{}'::jsonb) || '{"routine_auto_penalty": 2.0, "notes": "Use Claude subscription for strong fit, but reserve Opus-heavy work for protected/escalation paths."}'::jsonb
        WHERE provider = 'claude'
        """
    )
    op.execute(
        """
        UPDATE provider_entitlements
        SET metadata = COALESCE(metadata, '{}'::jsonb) || '{"routine_auto_penalty": 8.0, "notes": "Reserve Codex subscription for protected, verification, escalation, or explicit quality-biased routing."}'::jsonb
        WHERE provider = 'codex'
        """
    )
    op.execute(
        """
        UPDATE provider_entitlements
        SET metadata = COALESCE(metadata, '{}'::jsonb) || '{"coding_auto_bonus": 4.0, "code_review_auto_bonus": 2.0, "noncoding_auto_penalty": 5.0, "notes": "Preferred routine coding subscription path while Codex quota is conserved."}'::jsonb
        WHERE provider = 'kimi-code'
        """
    )
    op.execute(
        """
        UPDATE provider_entitlements
        SET metadata = COALESCE(metadata, '{}'::jsonb) || '{"routine_auto_bonus": 2.0, "planning_auto_bonus": 4.0, "reasoning_auto_bonus": 2.0, "prompt_auto_bonus": 2.0, "notes": "Preferred routine planning/reasoning subscription path when fit is close."}'::jsonb
        WHERE provider = 'minimax'
        """
    )
    op.execute(
        """
        UPDATE provider_entitlements
        SET metadata = COALESCE(metadata, '{}'::jsonb) || '{"routine_auto_bonus": 1.0, "utility_auto_bonus": 8.0, "vision_auto_bonus": 3.0, "notes": "Useful low-cost/free-tier utility path."}'::jsonb
        WHERE provider = 'gemini'
        """
    )
    op.execute(
        """
        DELETE FROM agent_workload_routing_modes
        WHERE owner = 'startup_seed'
          AND reason = 'Initial low-risk adaptive routing canary'
        """
    )


def downgrade() -> None:
    op.alter_column(
        "workload_profiles",
        "default_routing_mode",
        server_default=sa.text("'auto_shadow'"),
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.alter_column(
        "agent_routing_profiles",
        "default_routing_mode",
        server_default=sa.text("'auto_shadow'"),
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.execute(
        f"""
        UPDATE workload_profiles
        SET default_routing_mode = 'auto_shadow'
        WHERE key IN ({_quoted(AUTO_WORKLOADS)})
        """
    )
    op.execute(
        f"""
        UPDATE agent_routing_profiles
        SET
            default_routing_mode = 'auto_shadow',
            exploration_policy = 'shadow_only'
        WHERE agent_slug NOT IN ({_quoted(PROTECTED_AGENT_SLUGS)})
          AND COALESCE(metadata ->> 'source', '') = 'auto-routing-enable-v1'
        """
    )
    op.execute(
        """
        INSERT INTO agent_workload_routing_modes
            (agent_slug, workload_profile, routing_mode, canary_percent, reason, owner, enabled)
        VALUES
            ('note-formatter', 'summarization', 'auto_canary', 5, 'Initial low-risk adaptive routing canary', 'startup_seed', true),
            ('note-titler', 'summarization', 'auto_canary', 5, 'Initial low-risk adaptive routing canary', 'startup_seed', true),
            ('summarizer', 'summarization', 'auto_canary', 5, 'Initial low-risk adaptive routing canary', 'startup_seed', true)
        ON CONFLICT (agent_slug, workload_profile) DO NOTHING
        """
    )
    op.execute("DELETE FROM workload_profiles WHERE key = 'planning'")
