"""unify_startup_consumer_profiles

Revision ID: k7l8m9n0o1p2
Revises: j6k7l8m9n0o1
Create Date: 2026-05-10 00:00:00.000000

Collapses the three per-CLI startup consumer profiles
(claude_session_start, codex_startup, gemini_startup) into a single unified
`agent_startup` profile. Codex's curated override set wins on conflict —
Claude/Gemini override rows for the same source_id are dropped, since the
agentic-cli-startup-core prompt is now memory-tier-driven for all CLIs.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "k7l8m9n0o1p2"
down_revision: str | Sequence[str] | None = "j6k7l8m9n0o1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop Claude- and Gemini-only overrides; their counterparts in codex_startup
    # (or absence thereof) define the unified set.
    op.execute(
        """
        DELETE FROM runtime_context_overrides
        WHERE consumer_profile IN ('claude_session_start', 'gemini_startup')
        """
    )
    # Rename the surviving codex_startup rows to agent_startup.
    op.execute(
        """
        UPDATE runtime_context_overrides
        SET consumer_profile = 'agent_startup'
        WHERE consumer_profile = 'codex_startup'
        """
    )


def downgrade() -> None:
    # Best-effort revert: restore codex_startup; Claude/Gemini-only rows that
    # were dropped are not recoverable here.
    op.execute(
        """
        UPDATE runtime_context_overrides
        SET consumer_profile = 'codex_startup'
        WHERE consumer_profile = 'agent_startup'
        """
    )
