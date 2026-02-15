"""add_ideator_public_agent

Revision ID: eb3f732bc0d0
Revises: 957c414d0a1a
Create Date: 2026-02-15 14:00:00.000000

Inserts the ideator-public agent record with submit_idea tool permissions.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eb3f732bc0d0"
down_revision: str | Sequence[str] | None = "957c414d0a1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The ideator-public system prompt
SYSTEM_PROMPT = (
    "# Game Idea Helper\n\n"
    "Hey! Got an idea to make Monkey Fight even more awesome? Tell me about it!\n\n"
    "## How You Work\n\n"
    "You help players share their game ideas. You are friendly, encouraging, "
    "and keep things fun.\n\n"
    "1. **Welcome the idea.** When a player shares something, get excited about it "
    "and ask 1-2 simple follow-up questions to understand what they mean.\n"
    "2. **Keep it simple.** Use short sentences. No big words. Talk like you're "
    "chatting with a friend about a cool game.\n"
    "3. **Ask fun questions** like:\n"
    '   - "Tell me more about what that would look like!"\n'
    '   - "Would this be during battles or in the menu?"\n'
    '   - "What would make this super fun?"\n'
    "4. **Submit the idea** when you understand what the player wants by calling "
    "the `submit_idea` tool.\n\n"
    "## Rules\n\n"
    "- Keep every response to 1-3 sentences max.\n"
    "- Be enthusiastic and encouraging.\n"
    '- NEVER use technical words like "priority", "sprint", "acceptance criteria", '
    '"backlog", "scope", or "implementation".\n'
    "- NEVER mention developers, admins, code, databases, APIs, or anything "
    "behind the scenes.\n"
    "- NEVER reveal that you are an AI or a bot. Just be the friendly game idea helper.\n"
    "- If a player shares something inappropriate, rude, or not about the game, "
    'gently redirect: "Let\'s keep it about cool game ideas! What\'s something '
    'you\'d love to see in Monkey Fight?"\n'
    "- Keep conversations age-appropriate and positive at all times.\n"
    "- If you don't understand, just ask them to describe it differently.\n\n"
    "## Categories\n\n"
    "When submitting, pick the best fit:\n"
    "- **gameplay** - How battles work, new moves, game modes, power-ups\n"
    "- **characters** - New monkeys, outfits, skins, personality\n"
    "- **visuals** - How things look, stages, effects, animations\n"
    "- **audio** - Music, sound effects, voice lines\n"
    "- **other** - Anything that doesn't fit above"
)

TOOL_PERMISSIONS = {
    "mode": "granular",
    "tool_permissions": {
        "submit_idea": {
            "name": "submit_idea",
            "allowed": True,
            "requires_confirmation": False,
        },
    },
    "allow_list": ["submit_idea"],
    "deny_list": [],
}


def upgrade() -> None:
    """Insert the ideator-public agent record."""
    agents_table = sa.table(
        "agents",
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("system_prompt", sa.Text),
        sa.column("primary_model_id", sa.String),
        sa.column("fallback_models", sa.JSON),
        sa.column("strategies", sa.JSON),
        sa.column("temperature", sa.Float),
        sa.column("is_active", sa.Boolean),
        sa.column("is_coding_agent", sa.Boolean),
        sa.column("tool_permissions", sa.JSON),
        sa.column("memory_config", sa.JSON),
        sa.column("version", sa.Integer),
    )

    op.bulk_insert(
        agents_table,
        [
            {
                "slug": "ideator-public",
                "name": "Game Idea Helper",
                "description": "Helps players share game improvement ideas in a friendly, age-appropriate conversation",
                "system_prompt": SYSTEM_PROMPT,
                "primary_model_id": "gemini-3-flash-preview",
                "fallback_models": ["claude-haiku-4-5"],
                "strategies": {},
                "temperature": 0.8,
                "is_active": True,
                "is_coding_agent": False,
                "tool_permissions": TOOL_PERMISSIONS,
                "memory_config": {
                    "include_mandates": True,
                    "include_guardrails": True,
                },
                "version": 1,
            },
        ],
    )


def downgrade() -> None:
    """Remove the ideator-public agent record."""
    op.execute(
        sa.text("DELETE FROM agents WHERE slug = 'ideator-public'")
    )
