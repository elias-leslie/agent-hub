"""Drop the retired agent feedback tables and the work-chat feedback binding.

Revision ID: e20c973d117c
Revises: c154cf867446
Create Date: 2026-10-27

Agent feedback is retired: actionable issues are SummitFlow tasks. Removes tables
feedback_votes and feedback_items, and the never-populated session_bindings.feedback_id
column with its index. The historical rows stay recoverable from the daily pg_dumpall
in the Google Drive "postgres" restic job (`st backup restore postgres`).

The agent-hub.feedback_cleanup automation definition and profile are runtime rows, so
this migration leaves them alone (a guard test forbids definition writes); the profile
was disabled through `st automations disable`. Upgrade is idempotent.

Downgrade recreates the empty tables, column and index. Rows restore from the backup.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e20c973d117c"
down_revision: str | Sequence[str] | None = "c154cf867446"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.feedback_votes")
    op.execute("DROP TABLE IF EXISTS public.feedback_items")
    op.execute("DROP INDEX IF EXISTS public.ix_session_bindings_feedback_id")
    op.execute("ALTER TABLE public.session_bindings DROP COLUMN IF EXISTS feedback_id")


_DOWNGRADE_STATEMENTS = (
    "ALTER TABLE public.session_bindings ADD COLUMN IF NOT EXISTS feedback_id varchar(100)",
    "CREATE INDEX IF NOT EXISTS ix_session_bindings_feedback_id ON public.session_bindings (feedback_id)",
    """CREATE TABLE IF NOT EXISTS public.feedback_items (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    component_id varchar(50) NOT NULL,
    feedback_type varchar(20) NOT NULL,
    title varchar(200) NOT NULL,
    description text,
    severity varchar(10),
    status varchar(20) NOT NULL DEFAULT 'open',
    project_id varchar(50) NOT NULL,
    created_by_session_id varchar(36),
    agent_slug varchar(100),
    model_used varchar(50),
    session_type varchar(50),
    resolved_at timestamptz,
    resolution_note text,
    vote_count integer NOT NULL DEFAULT 1,
    linked_task_id varchar(50),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('english'::regconfig, COALESCE(title, '')::text || ' ' || COALESCE(description, ''))
    ) STORED,
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    independent_run_count integer NOT NULL DEFAULT 0,
    affected_roles jsonb NOT NULL DEFAULT '[]'::jsonb,
    affected_projects jsonb NOT NULL DEFAULT '[]'::jsonb,
    merged_into_id uuid,
    CONSTRAINT pk_feedback_items PRIMARY KEY (id),
    CONSTRAINT ck_feedback_items_ck_feedback_items_status
        CHECK (status IN ('open', 'acknowledged', 'resolved', 'wont_fix', 'archived')),
    CONSTRAINT ck_feedback_items_ck_feedback_items_type
        CHECK (feedback_type IN ('friction', 'idea', 'improvement', 'praise')),
    CONSTRAINT fk_feedback_items_sessions_created_by_session_id
        FOREIGN KEY (created_by_session_id) REFERENCES public.sessions(id) ON DELETE SET NULL,
    CONSTRAINT fk_feedback_items_merged_into
        FOREIGN KEY (merged_into_id) REFERENCES public.feedback_items(id) ON DELETE CASCADE
)""",
    "CREATE INDEX IF NOT EXISTS idx_feedback_items_component ON public.feedback_items (component_id)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_items_created ON public.feedback_items (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_items_project ON public.feedback_items (project_id)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_items_search ON public.feedback_items USING gin (search_vector)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_items_status ON public.feedback_items (status)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_items_type ON public.feedback_items (feedback_type)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_items_votes ON public.feedback_items (vote_count DESC)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_items_last_seen ON public.feedback_items (last_seen_at)",
    """CREATE TABLE IF NOT EXISTS public.feedback_votes (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    feedback_item_id uuid NOT NULL,
    session_id varchar(36),
    comment text,
    agent_slug varchar(100),
    model_used varchar(50),
    created_at timestamptz NOT NULL DEFAULT now(),
    occurrence_id varchar(160) NOT NULL,
    source_project_id varchar(50),
    run_ref varchar(200),
    role varchar(100),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    consequence text,
    workaround text,
    evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_kind varchar(30) NOT NULL DEFAULT 'report',
    CONSTRAINT pk_feedback_votes PRIMARY KEY (id),
    CONSTRAINT uq_feedback_votes_occurrence UNIQUE (occurrence_id),
    CONSTRAINT fk_feedback_votes_feedback_items_feedback_item_id
        FOREIGN KEY (feedback_item_id) REFERENCES public.feedback_items(id) ON DELETE CASCADE,
    CONSTRAINT fk_feedback_votes_session
        FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE SET NULL
)""",
    "CREATE INDEX IF NOT EXISTS idx_feedback_votes_item ON public.feedback_votes (feedback_item_id)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_votes_session ON public.feedback_votes (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_votes_source_project ON public.feedback_votes (source_project_id, feedback_item_id)",
)


def downgrade() -> None:
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)
