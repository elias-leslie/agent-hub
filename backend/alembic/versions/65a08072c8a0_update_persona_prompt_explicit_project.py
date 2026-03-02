"""Update persona system_prompt to require explicit -P on creation commands.

Revision ID: 65a08072c8a0
Revises: 4df8bb79ca83
Create Date: 2026-03-01
"""

from sqlalchemy import text

from alembic import op

revision = "65a08072c8a0"
down_revision = "4df8bb79ca83"
branch_labels = None
depends_on = None

# Pairs of (old_text, new_text) to apply to the persona system_prompt
_REPLACEMENTS = [
    (
        "- `st create 'title' --description 'desc' --priority P2` — create tasks\n",
        "- `st -P <project> create 'title' --description 'desc' --priority P2` — create tasks\n",
    ),
    (
        "- `st create '<title>' -t <type> -p <priority> -l '<labels>'` — create task\n",
        "- `st -P <project> create '<title>' -t <type> -p <priority> -l '<labels>'` — create task\n",
    ),
    (
        "- `st bug '<title>' -d '<desc>' -p 2` — quick bug creation\n",
        "- `st -P <project> bug '<title>' -d '<desc>' -p 2` — quick bug creation\n",
    ),
    (
        "- `st idea '<desc>'` — quick idea capture\n",
        "- `st -P <project> idea '<desc>'` — quick idea capture\n",
    ),
]

_REVERSE_REPLACEMENTS = [(new, old) for old, new in _REPLACEMENTS]


def _apply_replacements(replacements: list[tuple[str, str]]) -> None:
    """Apply text replacements to the persona agent's system_prompt."""
    conn = op.get_bind()
    result = conn.execute(text("SELECT system_prompt FROM agents WHERE slug = 'persona'"))
    row = result.fetchone()
    if not row or not row[0]:
        return
    prompt = row[0]
    for old, new in replacements:
        prompt = prompt.replace(old, new)
    conn.execute(
        text("UPDATE agents SET system_prompt = :prompt WHERE slug = 'persona'"),
        {"prompt": prompt},
    )


def upgrade() -> None:
    _apply_replacements(_REPLACEMENTS)


def downgrade() -> None:
    _apply_replacements(_REVERSE_REPLACEMENTS)
