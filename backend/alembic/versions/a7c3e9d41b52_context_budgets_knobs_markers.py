"""Context budgets, config knobs and the context_markers view.

Revision ID: a7c3e9d41b52
Revises: e8b3d6f1a2c4

context_budgets: one warn level per (harness or '*', role or '*') plus one global jump_pct, defaults above the
2026-11-01 medians. context_knobs: our config files that change what a harness loads (named in `why`).
context_markers: the things that can move a cell's context in time order (a view, no data of its own).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c3e9d41b52"
down_revision: str | Sequence[str] | None = "e8b3d6f1a2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Warn levels sit above each harness's first-turn medians of 2026-11-01 (Claude ~48K, Codex ~22K, Pi ~8K).
BUDGETS = [
    ("*", "*", 60000, 25, "Fallback for a harness with no row of its own. jump_pct: the one global step threshold."),
    ("claude", "*", 60000, None, None),
    ("codex", "*", 32000, None, None),
    ("pi", "*", 12000, None, None),
]
KNOBS = [
    ("lane-tools.json", "claude", "*", "/srv/workspaces/projects/aico", "tether/src/lifecycle/tui/lane-tools.json",
     "Tether starts launched Claude Code sessions without the tools and listings their role did not use."),
]

MARKERS_VIEW_SQL = """
CREATE VIEW context_markers AS
WITH delivered AS (
    SELECT DISTINCT b->>'source_type' AS source_type, b->>'source_id' AS source_id
    FROM context_deliveries d CROSS JOIN LATERAL jsonb_array_elements(d.blocks) AS b
),
sessions AS (
    SELECT harness, work_role, launch_mode, model, harness_version, config_fp, first_turn_at,
           lag(config_fp) OVER w AS prev_fp
    FROM usage_sessions
    WHERE first_turn_at IS NOT NULL AND harness IS NOT NULL
    WINDOW w AS (PARTITION BY harness, work_role, launch_mode, model ORDER BY first_turn_at)
)
SELECT r.created_at AS at, 'memory'::text AS kind, NULL::text AS harness, NULL::text AS work_role,
       NULL::text AS launch_mode, r.memory_uuid AS ref, COALESCE(NULLIF(r.name, ''), r.summary, r.memory_uuid) AS label,
       jsonb_build_object('action', r.action, 'version', r.version, 'scope', r.scope, 'tier', r.tier,
                          'tokens', r.token_count, 'writer_kind', r.writer_kind, 'writer_session', r.writer_session,
                          'changed_by', r.changed_by) AS detail
FROM memory_revisions r JOIN delivered d ON d.source_type = 'memory' AND d.source_id = r.memory_uuid
UNION ALL
SELECT r.created_at, 'prompt', NULL, NULL, NULL, r.prompt_slug, r.prompt_name,
       jsonb_build_object('action', r.action, 'is_global', r.is_global, 'writer_kind', r.writer_kind,
                          'writer_session', r.writer_session, 'changed_by', r.changed_by)
FROM prompt_revisions r JOIN delivered d ON d.source_type = 'prompt' AND d.source_id = r.prompt_slug
UNION ALL
SELECT v.first_at, 'harness_version', v.harness, NULL, NULL, v.harness_version, v.harness || ' ' || v.harness_version,
       jsonb_build_object('first_sighting', true)
FROM (SELECT harness, harness_version, min(first_turn_at) AS first_at FROM usage_sessions
      WHERE harness IS NOT NULL AND harness_version IS NOT NULL AND first_turn_at IS NOT NULL
      GROUP BY harness, harness_version) v
UNION ALL
SELECT first_turn_at, 'config', harness, work_role, launch_mode, config_fp, 'config ' || left(config_fp, 8),
       jsonb_build_object('from_fp', prev_fp, 'model', model, 'version', harness_version)
FROM sessions WHERE config_fp IS NOT NULL AND config_fp IS DISTINCT FROM prev_fp
UNION ALL
SELECT c.created_at, 'placement', NULL, NULL, NULL, c.id,
       COALESCE(c.payload::jsonb #>> '{context,consumer_profile}', 'placement') || ' placements',
       jsonb_build_object('actor', c.actor, 'project', c.payload::jsonb #>> '{context,project_id}')
FROM context_records c
WHERE c.kind = 'change' AND (c.payload::jsonb -> 'before_placements') IS DISTINCT FROM (c.payload::jsonb -> 'after_placements')
"""


def upgrade() -> None:
    budgets = op.create_table(
        "context_budgets",
        sa.Column("harness", sa.String(20), nullable=False),
        sa.Column("role", sa.String(80), nullable=False),
        sa.Column("warn_tokens", sa.Integer(), nullable=False),
        sa.Column("jump_pct", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("harness", "role"),
        sa.CheckConstraint("jump_pct IS NULL OR (harness = '*' AND role = '*')", name="ck_context_budgets_jump_global"),
        sa.CheckConstraint("warn_tokens > 0", name="ck_context_budgets_warn_positive"),
    )
    op.bulk_insert(budgets, [
        {"harness": h, "role": r, "warn_tokens": w, "jump_pct": j, "note": n} for h, r, w, j, n in BUDGETS
    ])
    knobs = op.create_table(
        "context_knobs",
        sa.Column("name", sa.String(100), primary_key=True),
        sa.Column("harness", sa.String(20), nullable=False, server_default="*"),
        sa.Column("role", sa.String(80), nullable=False, server_default="*"),
        sa.Column("repo_path", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.bulk_insert(knobs, [
        {"name": n, "harness": h, "role": r, "repo_path": rp, "file_path": fp, "note": note} for n, h, r, rp, fp, note in KNOBS
    ])
    op.execute(MARKERS_VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS context_markers")
    op.drop_table("context_knobs")
    op.drop_table("context_budgets")
