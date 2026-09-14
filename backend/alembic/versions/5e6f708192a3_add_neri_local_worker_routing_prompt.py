"""Add shared Neri local-worker routing guidance.

Revision ID: 5e6f708192a3
Revises: 4d5e6f708192
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "5e6f708192a3"
down_revision: str | Sequence[str] | None = "4d5e6f708192"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROMPT_SLUG = "neri-local-worker-routing"
_CONTENT = """# Neri local-worker routing

Neri Local Candidate is experimental passive assistance, not a research operator or reviewer. Before delegation, inspect its exact runtime status and persisted task-family benchmark evidence through the current ST capabilities. Initially no task family is promoted. Assign only a task family whose locked evaluation and independent audit explicitly mark it promoted.

Every request must use the bounded local-worker interface with a sanitized objective, referenced evidence items and constraints. Never send credentials, flags, private challenge material, confidential raw logs or executable payloads. The worker has no network, shell, tools, memory, session continuation, fallback, scope authority, live-target authority, report-submission authority or promotion authority. Treat its response as an inert draft and independently review it before it affects Neri or Learn-o-Tron state.

Keep novel vulnerability reasoning, live authorized target work, final validity/impact/severity, independent review and external commitments on their existing frontier-model and owner routes. A failed or unavailable local run fails visibly and stays local; never silently reroute the same packet to a cloud fallback. Record actual effective model, artifact/runtime identity, harness arm and reviewer corrections when local output contributes to work.
"""


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            INSERT INTO prompts (
                slug, name, content, description,
                is_global, enabled, exclude_agents,
                prompt_type, deletion_locked
            )
            VALUES (
                :slug, 'Neri Local Worker Routing', :content,
                'Cross-surface delegation limits for Neri local-model candidates.',
                FALSE, TRUE, CAST('[]' AS JSON), 'standard', TRUE
            )
            ON CONFLICT (slug) DO NOTHING
            """
        ),
        {"slug": _PROMPT_SLUG, "content": _CONTENT},
    )
    conn.execute(
        text(
            """
            INSERT INTO agent_prompts (agent_id, prompt_id, role, priority)
            SELECT a.id, p.id, 'system', 50
            FROM agents a, prompts p
            WHERE a.slug = 'neri-orchestrator' AND p.slug = :prompt_slug
              AND NOT EXISTS (
                SELECT 1 FROM agent_prompts ap
                WHERE ap.agent_id = a.id AND ap.prompt_id = p.id
              )
            """
        ),
        {"prompt_slug": _PROMPT_SLUG},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            "DELETE FROM agent_prompts ap USING prompts p "
            "WHERE ap.prompt_id = p.id AND p.slug = :slug"
        ),
        {"slug": _PROMPT_SLUG},
    )
    conn.execute(text("DELETE FROM prompts WHERE slug = :slug"), {"slug": _PROMPT_SLUG})
