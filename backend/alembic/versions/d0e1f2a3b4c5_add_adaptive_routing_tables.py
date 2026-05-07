"""add_adaptive_routing_tables

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b5
Create Date: 2026-05-07 20:20:00.000000
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CRITICAL_AGENT_SLUGS = (
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

DIMENSIONS = (
    ("coding", "Coding", "quality", "score", "up", 0.20),
    ("swe_agentic", "SWE Agentic", "quality", "score", "up", 0.16),
    ("code_review", "Code Review", "quality", "score", "up", 0.14),
    ("planning_orchestration", "Planning/Orchestration", "quality", "score", "up", 0.16),
    ("reasoning", "Reasoning", "quality", "score", "up", 0.16),
    ("tool_use", "Tool Use", "quality", "score", "up", 0.14),
    ("instruction", "Instruction Following", "quality", "score", "up", 0.12),
    ("strict_json", "Strict JSON", "quality", "score", "up", 0.12),
    ("math", "Math", "quality", "score", "up", 0.10),
    ("data_analysis", "Data Analysis", "quality", "score", "up", 0.12),
    ("data_research", "Data Research", "quality", "score", "up", 0.12),
    ("financial_analysis", "Financial Analysis", "quality", "score", "up", 0.20),
    ("market_analysis", "Market Analysis", "quality", "score", "up", 0.18),
    ("verification", "Verification", "quality", "score", "up", 0.18),
    ("prompt_building", "Prompt Building", "quality", "score", "up", 0.10),
    ("summarization", "Summarization", "quality", "score", "up", 0.08),
    ("memory_curation", "Memory Curation", "quality", "score", "up", 0.08),
    ("ux_design", "UX Design", "quality", "score", "up", 0.12),
    ("vision", "Vision", "modality", "boolean", "up", 0.0),
    ("image_generation", "Image Generation", "modality", "boolean", "up", 0.0),
    ("image_editing", "Image Editing", "modality", "boolean", "up", 0.0),
    ("audio", "Audio", "modality", "boolean", "up", 0.0),
    ("pdf", "PDF", "modality", "boolean", "up", 0.0),
    ("long_context", "Long Context", "ops", "score", "up", 0.06),
    ("latency", "Latency", "ops", "score", "up", 0.05),
    ("reliability", "Reliability", "ops", "score", "up", 0.10),
    ("subscription_backed", "Subscription Backed", "ops", "boolean", "up", 0.0),
)

WORKLOADS = (
    ("general", "General", {}, {}, "normal", "optional", "auto_shadow"),
    ("jenny_planning", "Jenny Planning", {"planning_orchestration": 1.0, "tool_use": 0.7, "reasoning": 0.8}, {}, "critical", "required", "manual_locked"),
    ("coding_impl", "Coding Implementation", {"coding": 1.0, "swe_agentic": 0.9, "tool_use": 0.7}, {"tool_use": True}, "normal", "optional", "auto_shadow"),
    ("code_review", "Code Review", {"code_review": 1.0, "reasoning": 0.8, "strict_json": 0.4}, {}, "elevated", "optional", "auto_shadow"),
    ("verifier", "Verifier", {"verification": 1.0, "reasoning": 0.9, "strict_json": 0.8}, {}, "critical", "required", "manual_locked"),
    ("finance_research", "Finance Research", {"financial_analysis": 1.0, "data_research": 0.8, "reasoning": 0.9}, {}, "critical", "required", "manual_locked"),
    ("trade_strategy", "Trade Strategy", {"financial_analysis": 1.0, "market_analysis": 0.9, "reasoning": 1.0}, {}, "critical", "required", "manual_locked"),
    ("market_scan", "Market Scan", {"market_analysis": 1.0, "data_research": 0.8, "summarization": 0.4}, {}, "critical", "required", "manual_locked"),
    ("data_analysis", "Data Analysis", {"data_analysis": 1.0, "math": 0.6, "reasoning": 0.6}, {}, "normal", "optional", "auto_shadow"),
    ("deep_research", "Deep Research", {"data_research": 1.0, "reasoning": 0.8, "long_context": 0.6}, {}, "elevated", "optional", "auto_shadow"),
    ("prompt_building", "Prompt Building", {"prompt_building": 1.0, "instruction": 0.8}, {}, "normal", "optional", "auto_shadow"),
    ("summarization", "Summarization", {"summarization": 1.0, "instruction": 0.5, "latency": 0.4}, {}, "low", "optional", "auto_shadow"),
    ("memory_curation", "Memory Curation", {"memory_curation": 1.0, "summarization": 0.7, "instruction": 0.6}, {}, "normal", "optional", "auto_shadow"),
    ("ui_design", "UI Design", {"ux_design": 1.0, "vision": 0.5, "instruction": 0.5}, {}, "normal", "optional", "auto_shadow"),
    ("vision_qa", "Vision QA", {"vision": 1.0, "reasoning": 0.5}, {"vision": True}, "normal", "optional", "auto_shadow"),
    ("image_generation", "Image Generation", {"image_generation": 1.0, "ux_design": 0.4}, {"image_generation": True}, "normal", "optional", "manual_locked"),
    ("voice_response", "Voice Response", {"audio": 1.0, "latency": 0.7, "instruction": 0.6}, {"audio": True}, "normal", "optional", "auto_shadow"),
)


def upgrade() -> None:
    op.create_table(
        "capability_dimensions",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("value_type", sa.String(length=20), nullable=False, server_default="score"),
        sa.Column("direction", sa.String(length=10), nullable=False, server_default="up"),
        sa.Column("default_weight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_capability_dimensions_category", "capability_dimensions", ["category"])

    op.create_table(
        "workload_profiles",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("requirement_deltas", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("hard_constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("risk_tier", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("verifier_policy", sa.String(length=40), nullable=False, server_default="optional"),
        sa.Column("default_routing_mode", sa.String(length=20), nullable=False, server_default="auto_shadow"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "agent_routing_profiles",
        sa.Column("agent_slug", sa.String(length=100), sa.ForeignKey("agents.slug", ondelete="CASCADE"), primary_key=True),
        sa.Column("default_routing_mode", sa.String(length=20), nullable=False, server_default="auto_shadow"),
        sa.Column("risk_tier", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("cost_policy", sa.String(length=40), nullable=False, server_default="subscription_first"),
        sa.Column("subscription_policy", sa.String(length=40), nullable=False, server_default="prefer_subscription"),
        sa.Column("exploration_policy", sa.String(length=40), nullable=False, server_default="shadow_only"),
        sa.Column("quality_floor", sa.Float(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_routing_profiles_mode", "agent_routing_profiles", ["default_routing_mode"])

    op.create_table(
        "agent_workload_routing_modes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_slug", sa.String(length=100), sa.ForeignKey("agents.slug", ondelete="CASCADE"), nullable=False),
        sa.Column("workload_profile", sa.String(length=100), sa.ForeignKey("workload_profiles.key", ondelete="CASCADE"), nullable=False),
        sa.Column("routing_mode", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("owner", sa.String(length=100), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("agent_slug", "workload_profile", name="uq_agent_workload_routing_mode"),
    )
    op.create_index("ix_agent_workload_routing_modes_agent_slug", "agent_workload_routing_modes", ["agent_slug"])
    op.create_index("ix_agent_workload_routing_modes_workload_profile", "agent_workload_routing_modes", ["workload_profile"])

    op.create_table(
        "manual_model_routes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_slug", sa.String(length=100), sa.ForeignKey("agents.slug", ondelete="CASCADE"), nullable=False),
        sa.Column("workload_profile", sa.String(length=100), sa.ForeignKey("workload_profiles.key", ondelete="SET NULL"), nullable=True),
        sa.Column("primary_model_id", sa.String(length=200), sa.ForeignKey("models.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("fallback_models", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("escalation_model_id", sa.String(length=200), sa.ForeignKey("models.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("owner", sa.String(length=100), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("allow_health_fallback", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_manual_model_routes_agent_slug", "manual_model_routes", ["agent_slug"])
    op.create_index("ix_manual_model_routes_workload_profile", "manual_model_routes", ["workload_profile"])
    op.create_index("ix_manual_model_routes_agent_workload", "manual_model_routes", ["agent_slug", "workload_profile", "enabled"])

    op.create_table(
        "provider_entitlements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("auth_mode", sa.String(length=40), nullable=False),
        sa.Column("plan", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="unknown"),
        sa.Column("quota_units", sa.Float(), nullable=True),
        sa.Column("quota_window", sa.String(length=40), nullable=True),
        sa.Column("auth_secret_ref", sa.String(length=200), nullable=True),
        sa.Column("discovery_source", sa.String(length=100), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_provider_entitlements_provider", "provider_entitlements", ["provider"])
    op.create_index("ix_provider_entitlements_provider_status", "provider_entitlements", ["provider", "status", "enabled"])

    op.create_table(
        "model_availability",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_id", sa.String(length=200), sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("entitlement_id", sa.Integer(), sa.ForeignKey("provider_entitlements.id", ondelete="SET NULL"), nullable=True),
        sa.Column("discovered_name", sa.String(length=200), nullable=True),
        sa.Column("routable", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_smoke_status", sa.String(length=40), nullable=False, server_default="not_run"),
        sa.Column("last_smoke_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("capabilities_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("model_id", "provider", name="uq_model_availability_model_provider"),
    )
    op.create_index("ix_model_availability_model_id", "model_availability", ["model_id"])
    op.create_index("ix_model_availability_provider", "model_availability", ["provider"])
    op.create_index("ix_model_availability_routable", "model_availability", ["routable", "enabled"])

    op.create_table(
        "model_capability_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_id", sa.String(length=200), sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dimension_key", sa.String(length=100), sa.ForeignKey("capability_dimensions.key", ondelete="CASCADE"), nullable=False),
        sa.Column("numeric_score", sa.Float(), nullable=True),
        sa.Column("boolean_value", sa.Boolean(), nullable=True),
        sa.Column("text_value", sa.String(length=200), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="seed"),
        sa.Column("evidence_url", sa.Text(), nullable=True),
        sa.Column("benchmark_run_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("agent_benchmark_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_model_capability_scores_model_id", "model_capability_scores", ["model_id"])
    op.create_index("ix_model_capability_scores_dimension_key", "model_capability_scores", ["dimension_key"])
    op.create_index("ix_model_capability_model_dimension", "model_capability_scores", ["model_id", "dimension_key"])

    op.create_table(
        "routing_policy_versions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_routing_policy_versions_active", "routing_policy_versions", ["active"])

    op.create_table(
        "routing_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("request_id", sa.String(length=200), nullable=True),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("agent_slug", sa.String(length=100), nullable=False),
        sa.Column("workload_profile", sa.String(length=100), nullable=False),
        sa.Column("routing_mode", sa.String(length=20), nullable=False),
        sa.Column("input_features", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("candidates", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("chosen_model_id", sa.String(length=200), nullable=False),
        sa.Column("chosen_provider", sa.String(length=100), nullable=False),
        sa.Column("fallback_chain", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("score_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("policy_version_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("routing_policy_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("constraints_hit", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("manual_route_id", sa.Integer(), sa.ForeignKey("manual_model_routes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="selected"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_routing_decisions_request_id", "routing_decisions", ["request_id"])
    op.create_index("ix_routing_decisions_session_id", "routing_decisions", ["session_id"])
    op.create_index("ix_routing_decisions_agent_slug", "routing_decisions", ["agent_slug"])
    op.create_index("ix_routing_decisions_workload_profile", "routing_decisions", ["workload_profile"])
    op.create_index("ix_routing_decisions_routing_mode", "routing_decisions", ["routing_mode"])
    op.create_index("ix_routing_decisions_chosen_model_id", "routing_decisions", ["chosen_model_id"])
    op.create_index("ix_routing_decisions_status", "routing_decisions", ["status"])
    op.create_index("ix_routing_decisions_created_at", "routing_decisions", ["created_at"])
    op.create_index("ix_routing_decisions_agent_workload_created", "routing_decisions", ["agent_slug", "workload_profile", "created_at"])

    op.create_table(
        "model_workload_performance",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_slug", sa.String(length=100), nullable=True),
        sa.Column("workload_profile", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=200), sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rolling_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("pass_rate", sa.Float(), nullable=True),
        sa.Column("verifier_score", sa.Float(), nullable=True),
        sa.Column("strict_json_pass_rate", sa.Float(), nullable=True),
        sa.Column("fallback_rate", sa.Float(), nullable=True),
        sa.Column("timeout_rate", sa.Float(), nullable=True),
        sa.Column("p50_latency_ms", sa.Integer(), nullable=True),
        sa.Column("p95_latency_ms", sa.Integer(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_model_workload_performance_agent_slug", "model_workload_performance", ["agent_slug"])
    op.create_index("ix_model_workload_performance_workload_profile", "model_workload_performance", ["workload_profile"])
    op.create_index("ix_model_workload_performance_model_id", "model_workload_performance", ["model_id"])
    op.create_index("ix_model_workload_perf_lookup", "model_workload_performance", ["workload_profile", "agent_slug", "model_id"])

    _seed_initial_rows()


def _seed_initial_rows() -> None:
    conn = op.get_bind()
    for key, label, category, value_type, direction, weight in DIMENSIONS:
        conn.execute(
            sa.text(
                """
                INSERT INTO capability_dimensions
                    (key, label, category, value_type, direction, default_weight)
                VALUES
                    (:key, :label, :category, :value_type, :direction, :weight)
                ON CONFLICT (key) DO NOTHING
                """
            ),
            {
                "key": key,
                "label": label,
                "category": category,
                "value_type": value_type,
                "direction": direction,
                "weight": weight,
            },
        )

    for key, label, requirements, constraints, risk, verifier, mode in WORKLOADS:
        conn.execute(
            sa.text(
                """
                INSERT INTO workload_profiles
                    (key, label, requirement_deltas, hard_constraints, risk_tier, verifier_policy, default_routing_mode)
                VALUES
                    (:key, :label, CAST(:requirements AS jsonb), CAST(:constraints AS jsonb), :risk, :verifier, :mode)
                ON CONFLICT (key) DO NOTHING
                """
            ),
            {
                "key": key,
                "label": label,
                "requirements": json.dumps(requirements),
                "constraints": json.dumps(constraints),
                "risk": risk,
                "verifier": verifier,
                "mode": mode,
            },
        )

    critical_list = ", ".join(f"'{slug}'" for slug in CRITICAL_AGENT_SLUGS)
    conn.execute(
        sa.text(
            f"""
            INSERT INTO agent_routing_profiles
                (agent_slug, default_routing_mode, risk_tier, cost_policy, subscription_policy, exploration_policy, metadata)
            SELECT
                slug,
                CASE WHEN slug IN ({critical_list}) THEN 'manual_locked' ELSE 'auto_shadow' END,
                CASE WHEN slug IN ({critical_list}) THEN 'critical' ELSE 'normal' END,
                'subscription_first',
                'prefer_subscription',
                CASE WHEN slug IN ({critical_list}) THEN 'disabled' ELSE 'shadow_only' END,
                '{{"source":"migration"}}'::jsonb
            FROM agents
            WHERE is_active = true
            ON CONFLICT (agent_slug) DO NOTHING
            """
        )
    )

    conn.execute(
        sa.text(
            """
            INSERT INTO manual_model_routes
                (agent_slug, workload_profile, primary_model_id, fallback_models, escalation_model_id,
                 reason, owner, allow_health_fallback, enabled)
            SELECT
                slug,
                NULL,
                primary_model_id,
                COALESCE(fallback_models::jsonb, '[]'::jsonb),
                escalation_model_id,
                'Migrated from agents.primary_model_id/fallback_models',
                'migration',
                false,
                true
            FROM agents
            WHERE is_active = true
              AND primary_model_id IN (SELECT id FROM models)
              AND NOT EXISTS (
                  SELECT 1 FROM manual_model_routes mmr
                  WHERE mmr.agent_slug = agents.slug
                    AND mmr.workload_profile IS NULL
                    AND mmr.enabled = true
              )
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_model_workload_perf_lookup", table_name="model_workload_performance")
    op.drop_index("ix_model_workload_performance_model_id", table_name="model_workload_performance")
    op.drop_index("ix_model_workload_performance_workload_profile", table_name="model_workload_performance")
    op.drop_index("ix_model_workload_performance_agent_slug", table_name="model_workload_performance")
    op.drop_table("model_workload_performance")
    op.drop_index("ix_routing_decisions_agent_workload_created", table_name="routing_decisions")
    op.drop_index("ix_routing_decisions_created_at", table_name="routing_decisions")
    op.drop_index("ix_routing_decisions_status", table_name="routing_decisions")
    op.drop_index("ix_routing_decisions_chosen_model_id", table_name="routing_decisions")
    op.drop_index("ix_routing_decisions_routing_mode", table_name="routing_decisions")
    op.drop_index("ix_routing_decisions_workload_profile", table_name="routing_decisions")
    op.drop_index("ix_routing_decisions_agent_slug", table_name="routing_decisions")
    op.drop_index("ix_routing_decisions_session_id", table_name="routing_decisions")
    op.drop_index("ix_routing_decisions_request_id", table_name="routing_decisions")
    op.drop_table("routing_decisions")
    op.drop_index("ix_routing_policy_versions_active", table_name="routing_policy_versions")
    op.drop_table("routing_policy_versions")
    op.drop_index("ix_model_capability_model_dimension", table_name="model_capability_scores")
    op.drop_index("ix_model_capability_scores_dimension_key", table_name="model_capability_scores")
    op.drop_index("ix_model_capability_scores_model_id", table_name="model_capability_scores")
    op.drop_table("model_capability_scores")
    op.drop_index("ix_model_availability_routable", table_name="model_availability")
    op.drop_index("ix_model_availability_provider", table_name="model_availability")
    op.drop_index("ix_model_availability_model_id", table_name="model_availability")
    op.drop_table("model_availability")
    op.drop_index("ix_provider_entitlements_provider_status", table_name="provider_entitlements")
    op.drop_index("ix_provider_entitlements_provider", table_name="provider_entitlements")
    op.drop_table("provider_entitlements")
    op.drop_index("ix_manual_model_routes_agent_workload", table_name="manual_model_routes")
    op.drop_index("ix_manual_model_routes_workload_profile", table_name="manual_model_routes")
    op.drop_index("ix_manual_model_routes_agent_slug", table_name="manual_model_routes")
    op.drop_table("manual_model_routes")
    op.drop_index("ix_agent_workload_routing_modes_workload_profile", table_name="agent_workload_routing_modes")
    op.drop_index("ix_agent_workload_routing_modes_agent_slug", table_name="agent_workload_routing_modes")
    op.drop_table("agent_workload_routing_modes")
    op.drop_index("ix_agent_routing_profiles_mode", table_name="agent_routing_profiles")
    op.drop_table("agent_routing_profiles")
    op.drop_table("workload_profiles")
    op.drop_index("ix_capability_dimensions_category", table_name="capability_dimensions")
    op.drop_table("capability_dimensions")
