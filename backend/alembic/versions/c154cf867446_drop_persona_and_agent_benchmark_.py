"""Drop the persona subsystem and the agent benchmark subsystem.

Revision ID: c154cf867446
Revises: a7c2e4f6b8d0

The persona agent (Jenny) and the benchmark tables that tracked it are retired.
Everything was archived first to /srv/workspaces/archive/agent-hub-persona-2026-10-26/
(persona row, agent row, 19 prompts, benchmark experiments/runs/attempts, regression
clusters). Upgrade is idempotent.

Removes: tables persona, agent_regression_clusters, agent_benchmark_attempts,
agent_benchmark_runs, agent_benchmark_experiments. Agent and prompt rows are runtime
state, so this migration does not touch them (a guard test forbids it); the `persona`
agent row and its prompts (persona-*, jenny-autonomy-policy, completion-review-*) were
deleted from the live DB directly.
Sessions, request logs and other history that only carry agent_slug='persona' as
text are left untouched. agent_performance_logs stays; only its logged_by default
changes from 'persona' to 'agent'.

Downgrade recreates the empty tables and the old column default. Table rows restore
from the archive.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c154cf867446"
down_revision: str | Sequence[str] | None = "a7c2e4f6b8d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None



def upgrade() -> None:
    for table in (
        "agent_regression_clusters",
        "agent_benchmark_attempts",
        "agent_benchmark_runs",
        "agent_benchmark_experiments",
        "persona",
    ):
        op.execute(f"DROP TABLE IF EXISTS public.{table}")
    op.execute("ALTER TABLE agent_performance_logs ALTER COLUMN logged_by SET DEFAULT 'agent'")


_DOWNGRADE_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS public.persona (
    id serial NOT NULL,
    agent_id integer NOT NULL,
    name varchar(100) NOT NULL DEFAULT 'Johnny',
    personality text,
    voice_id varchar(200) DEFAULT 'en-US-AriaNeural',
    voice_enabled boolean DEFAULT false,
    avatar_url varchar(500),
    greeting text,
    version integer DEFAULT 1,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    user_context text,
    onboarding_complete boolean NOT NULL DEFAULT false,
    onboarding_phase varchar(20) NOT NULL DEFAULT 'not_started',
    session_reset_mode varchar(10) NOT NULL DEFAULT 'off',
    session_reset_hour integer NOT NULL DEFAULT 9,
    session_reset_idle_minutes integer NOT NULL DEFAULT 120,
    limits jsonb,
    onboarding_attempts integer NOT NULL DEFAULT 0,
    user_context_previous text,
    personality_previous text,
    execution_state varchar(16) NOT NULL DEFAULT 'active',
    user_profile jsonb,
    CONSTRAINT pk_persona PRIMARY KEY (id),
    CONSTRAINT fk_persona_agents_agent_id FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_persona_agent_id ON public.persona (agent_id)",
    """CREATE TABLE IF NOT EXISTS public.agent_benchmark_experiments (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    experiment_key varchar(120) NOT NULL,
    agent_slug varchar(100) NOT NULL,
    project_id varchar(100) NOT NULL,
    suite_id varchar(100) NOT NULL,
    name varchar(160) NOT NULL,
    hypothesis text,
    status varchar(20) NOT NULL DEFAULT 'open',
    decision varchar(20) NOT NULL DEFAULT 'hold',
    decision_reason text,
    baseline_label varchar(60) NOT NULL DEFAULT 'baseline',
    candidate_label varchar(60) NOT NULL DEFAULT 'candidate',
    min_runs_per_cohort integer NOT NULL DEFAULT 3,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_benchmark_experiments PRIMARY KEY (id),
    CONSTRAINT agent_benchmark_experiments_experiment_key_key UNIQUE (experiment_key)
)""",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_experiments_agent_slug ON public.agent_benchmark_experiments (agent_slug)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_experiments_agent_suite_created ON public.agent_benchmark_experiments (agent_slug, suite_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_experiments_experiment_key ON public.agent_benchmark_experiments (experiment_key)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_experiments_project_id ON public.agent_benchmark_experiments (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_experiments_status ON public.agent_benchmark_experiments (status)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_experiments_suite_id ON public.agent_benchmark_experiments (suite_id)",
    """CREATE TABLE IF NOT EXISTS public.agent_benchmark_runs (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    benchmark_id varchar(100) NOT NULL,
    agent_slug varchar(100) NOT NULL,
    project_id varchar(100) NOT NULL,
    suite_id varchar(100) NOT NULL,
    run_kind varchar(32) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'completed',
    models jsonb NOT NULL DEFAULT '[]'::jsonb,
    case_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    runs_per_case integer NOT NULL DEFAULT 1,
    use_memory boolean NOT NULL DEFAULT false,
    seed integer,
    avg_score double precision,
    pass_rate double precision,
    attempt_count integer NOT NULL DEFAULT 0,
    passed_attempt_count integer NOT NULL DEFAULT 0,
    infra_failure_count integer NOT NULL DEFAULT 0,
    config_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    experiment_id uuid,
    experiment_cohort varchar(20),
    CONSTRAINT pk_agent_benchmark_runs PRIMARY KEY (id),
    CONSTRAINT agent_benchmark_runs_benchmark_id_key UNIQUE (benchmark_id),
    CONSTRAINT fk_agent_benchmark_runs_agent_benchmark_experiments_exp_af13
        FOREIGN KEY (experiment_id) REFERENCES public.agent_benchmark_experiments(id) ON DELETE SET NULL
)""",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_runs_agent_slug ON public.agent_benchmark_runs (agent_slug)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_runs_agent_suite_completed ON public.agent_benchmark_runs (agent_slug, suite_id, completed_at)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_runs_benchmark_id ON public.agent_benchmark_runs (benchmark_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_runs_experiment_cohort ON public.agent_benchmark_runs (experiment_cohort)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_runs_experiment_id ON public.agent_benchmark_runs (experiment_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_runs_project_id ON public.agent_benchmark_runs (project_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_runs_run_kind ON public.agent_benchmark_runs (run_kind)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_runs_suite_id ON public.agent_benchmark_runs (suite_id)",
    """CREATE TABLE IF NOT EXISTS public.agent_benchmark_attempts (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    benchmark_run_id uuid NOT NULL,
    agent_slug varchar(100) NOT NULL,
    model_id varchar(200) NOT NULL,
    effective_model varchar(200),
    requested_model varchar(200),
    case_id varchar(100) NOT NULL,
    run_number integer NOT NULL,
    session_id varchar(100),
    provider varchar(100),
    latency_ms integer NOT NULL DEFAULT 0,
    input_tokens integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    total_tokens integer NOT NULL DEFAULT 0,
    turns integer NOT NULL DEFAULT 0,
    tool_calls_count integer NOT NULL DEFAULT 0,
    used_tool_names jsonb NOT NULL DEFAULT '[]'::jsonb,
    schema_valid boolean NOT NULL DEFAULT false,
    tool_requirement_met boolean NOT NULL DEFAULT true,
    correctness_score double precision NOT NULL DEFAULT 0,
    composite_score double precision NOT NULL DEFAULT 0,
    passed boolean NOT NULL DEFAULT false,
    infra_failure boolean NOT NULL DEFAULT false,
    failure_kind varchar(20),
    failure_detail text,
    fallback_used boolean NOT NULL DEFAULT false,
    primary_action varchar(32),
    should_dispatch boolean,
    should_close boolean,
    confidence varchar(16),
    summary text,
    raw_content text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_benchmark_attempts PRIMARY KEY (id),
    CONSTRAINT fk_agent_benchmark_attempts_agent_benchmark_runs_benchm_6ecd
        FOREIGN KEY (benchmark_run_id) REFERENCES public.agent_benchmark_runs(id) ON DELETE CASCADE
)""",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_attempts_agent_model_created ON public.agent_benchmark_attempts (agent_slug, model_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_attempts_agent_slug ON public.agent_benchmark_attempts (agent_slug)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_attempts_case_id ON public.agent_benchmark_attempts (case_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_attempts_model_id ON public.agent_benchmark_attempts (model_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_benchmark_attempts_run_case ON public.agent_benchmark_attempts (benchmark_run_id, case_id)",
    """CREATE TABLE IF NOT EXISTS public.agent_regression_clusters (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    agent_slug varchar(100) NOT NULL,
    suite_id varchar(100) NOT NULL,
    regression_key varchar(255) NOT NULL,
    case_id varchar(100) NOT NULL,
    failure_detail text NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'open',
    first_seen_run_id uuid,
    last_seen_run_id uuid,
    occurrence_count integer NOT NULL DEFAULT 0,
    latest_avg_score double precision,
    affected_models jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    opened_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_agent_regression_clusters PRIMARY KEY (id),
    CONSTRAINT uq_agent_regression_clusters_agent_suite_key UNIQUE (agent_slug, suite_id, regression_key),
    CONSTRAINT fk_agent_regression_clusters_agent_benchmark_runs_first_720e
        FOREIGN KEY (first_seen_run_id) REFERENCES public.agent_benchmark_runs(id) ON DELETE SET NULL,
    CONSTRAINT fk_agent_regression_clusters_agent_benchmark_runs_last__0e44
        FOREIGN KEY (last_seen_run_id) REFERENCES public.agent_benchmark_runs(id) ON DELETE SET NULL
)""",
    "CREATE INDEX IF NOT EXISTS ix_agent_regression_clusters_agent_slug ON public.agent_regression_clusters (agent_slug)",
    "CREATE INDEX IF NOT EXISTS ix_agent_regression_clusters_agent_suite_status ON public.agent_regression_clusters (agent_slug, suite_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_agent_regression_clusters_case_id ON public.agent_regression_clusters (case_id)",
    "CREATE INDEX IF NOT EXISTS ix_agent_regression_clusters_status ON public.agent_regression_clusters (status)",
    "CREATE INDEX IF NOT EXISTS ix_agent_regression_clusters_suite_id ON public.agent_regression_clusters (suite_id)",
    "ALTER TABLE agent_performance_logs ALTER COLUMN logged_by SET DEFAULT 'persona'",
)


def downgrade() -> None:
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
