"""drop_task_branch_line_from_wake_guidance

Revision ID: w7x8y9z0a1b2
Revises: v6w7x8y9z0a1
Create Date: 2026-05-18 00:00:00.000000

SummitFlow no longer creates per-task branches; `st claim`/`st done` work
directly on main and `st lease` handles parallel-agent coordination. The
persona-wake-guidance prompt still carried one residual line teaching the
persona to inspect "task branch" refs with git show/log/diff. Replace it
with the lease-aware guidance.

Only persona-wake-guidance is touched here. The other historically
problematic surfaces (persona-heartbeat-orchestrator content, agents.persona
system_prompt, persona.heartbeat_instructions column) have already been
overwritten or dropped by later migrations.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "w7x8y9z0a1b2"
down_revision: str | Sequence[str] | None = "v6w7x8y9z0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_LINE = (
    "- If task branch is not checked out here, inspect with `git show`, "
    "`git log`, or `git diff`. No `git checkout` here."
)
_NEW_LINE = (
    "- `st claim` / `st done` work directly on main; there are no per-task "
    "branches to inspect or check out. For parallel-agent file "
    "coordination, declare a scope with `st lease '<glob>'` and rely on the "
    "PreToolUse gate to block cross-agent writes."
)


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            "UPDATE prompts "
            "SET content = REPLACE(content, :old, :new), "
            "    updated_at = NOW() "
            "WHERE slug = 'persona-wake-guidance' "
            "  AND content LIKE :old_like"
        ),
        {"old": _OLD_LINE, "new": _NEW_LINE, "old_like": "%" + _OLD_LINE + "%"},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            "UPDATE prompts "
            "SET content = REPLACE(content, :new, :old), "
            "    updated_at = NOW() "
            "WHERE slug = 'persona-wake-guidance' "
            "  AND content LIKE :new_like"
        ),
        {"old": _OLD_LINE, "new": _NEW_LINE, "new_like": "%" + _NEW_LINE + "%"},
    )
