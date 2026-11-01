"""context_markers: a config marker is the first sighting of a request shape within one harness version.

Revision ID: d3b8f1a6c294
Revises: a7c3e9d41b52

The config marker compared each session with the one before it in (harness, role, launch mode, model). Two kinds of
session that run side by side in one cell (an older harness version still open next to a newer one, or two tool sets)
made the fingerprint alternate, and every swap showed as a "config" change. Now the partition includes the harness
version, a fingerprint marks only its first sighting there, and a session that has no previous fingerprint (the first
of its partition, or one that did not record a shape) is not a change. The detail names both fingerprints.

Only the view is replaced; no data changes. A later migration that alters a column the view pins must drop and
recreate it again (MARKERS_VIEW_SQL).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d3b8f1a6c294"
down_revision: str | Sequence[str] | None = "a7c3e9d41b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MARKERS_VIEW_SQL = """
CREATE VIEW context_markers AS
WITH delivered AS (
    SELECT DISTINCT b->>'source_type' AS source_type, b->>'source_id' AS source_id
    FROM context_deliveries d CROSS JOIN LATERAL jsonb_array_elements(d.blocks) AS b
),
sessions AS (
    SELECT harness, work_role, launch_mode, model, harness_version, config_fp, first_turn_at,
           lag(config_fp) OVER w AS prev_fp,
           row_number() OVER (PARTITION BY harness, work_role, launch_mode, model, harness_version, config_fp
                              ORDER BY first_turn_at) AS nth
    FROM usage_sessions
    WHERE first_turn_at IS NOT NULL AND harness IS NOT NULL
    WINDOW w AS (PARTITION BY harness, work_role, launch_mode, model, harness_version ORDER BY first_turn_at)
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
FROM sessions WHERE config_fp IS NOT NULL AND prev_fp IS NOT NULL AND config_fp <> prev_fp AND nth = 1
UNION ALL
SELECT c.created_at, 'placement', NULL, NULL, NULL, c.id,
       COALESCE(c.payload::jsonb #>> '{context,consumer_profile}', 'placement') || ' placements',
       jsonb_build_object('actor', c.actor, 'project', c.payload::jsonb #>> '{context,project_id}')
FROM context_records c
WHERE c.kind = 'change' AND (c.payload::jsonb -> 'before_placements') IS DISTINCT FROM (c.payload::jsonb -> 'after_placements')
"""


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS context_markers")
    op.execute(MARKERS_VIEW_SQL)


def downgrade() -> None:
    """The earlier view: any change from the previous session of (harness, role, launch mode, model) is a config marker."""
    old = (MARKERS_VIEW_SQL
           .replace(", harness_version, config_fp, first_turn_at,\n           lag(config_fp) OVER w AS prev_fp,\n"
                    "           row_number() OVER (PARTITION BY harness, work_role, launch_mode, model, harness_version, config_fp\n"
                    "                              ORDER BY first_turn_at) AS nth\n",
                    ", harness_version, config_fp, first_turn_at,\n           lag(config_fp) OVER w AS prev_fp\n")
           .replace("PARTITION BY harness, work_role, launch_mode, model, harness_version ORDER BY", "PARTITION BY harness, work_role, launch_mode, model ORDER BY")
           .replace("config_fp IS NOT NULL AND prev_fp IS NOT NULL AND config_fp <> prev_fp AND nth = 1",
                    "config_fp IS NOT NULL AND config_fp IS DISTINCT FROM prev_fp"))
    op.execute("DROP VIEW IF EXISTS context_markers")
    op.execute(old)
