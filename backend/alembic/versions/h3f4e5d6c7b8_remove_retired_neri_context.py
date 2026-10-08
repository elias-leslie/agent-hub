"""Remove retired Neri agents, their mirrors, and obsolete prompts.

Revision ID: h3f4e5d6c7b8
Revises: g2f3e4d5c6b7
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "h3f4e5d6c7b8"
down_revision: str | Sequence[str] | None = "g2f3e4d5c6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AGENTS = {
    "neri-local-candidate": "Neri Local Candidate",
    "neri-orchestrator": "Neri Orchestrator",
}
_PROMPTS = {
    "neri-local-candidate-system-prompt": "Neri Local Candidate System Prompt",
    "neri-local-worker-routing": "Neri Local Worker Routing",
    "neri-orchestrator-system-prompt": "Neri Orchestrator System Prompt",
}


def upgrade() -> None:
    bind = op.get_bind()
    # Missing retired rows are safe; a reused slug or extra owned data is not.
    for table, expected in (("agents", _AGENTS), ("prompts", _PROMPTS)):
        rows = bind.execute(
            sa.text(f"SELECT slug, name FROM {table} WHERE slug IN :slugs FOR UPDATE")
            .bindparams(sa.bindparam("slugs", expanding=True)),
            {"slugs": tuple(expected)},
        ).all()
        for slug, name in rows:
            if name != expected[slug]:
                raise RuntimeError(f"Retired Neri {table} identity changed: {slug}")

    parameters = {"agent_slugs": tuple(_AGENTS), "prompt_slugs": tuple(_PROMPTS)}
    owned_prompts = bind.execute(
        sa.text(
            "SELECT slug FROM prompts WHERE owner_agent_id IN "
            "(SELECT id FROM agents WHERE slug IN :agent_slugs) "
            "AND slug NOT IN :prompt_slugs"
        ).bindparams(
            sa.bindparam("agent_slugs", expanding=True),
            sa.bindparam("prompt_slugs", expanding=True),
        ),
        parameters,
    ).all()
    if owned_prompts:
        raise RuntimeError("Retired Neri agents own unexpected prompts; cleanup stopped")
    personas = bind.execute(
        sa.text(
            "SELECT id FROM persona WHERE agent_id IN "
            "(SELECT id FROM agents WHERE slug IN :agent_slugs)"
        ).bindparams(sa.bindparam("agent_slugs", expanding=True)),
        {"agent_slugs": tuple(_AGENTS)},
    ).all()
    if personas:
        raise RuntimeError("Retired Neri agents own unexpected personas; cleanup stopped")

    bind.execute(
        sa.text(
            "DELETE FROM agent_prompts WHERE prompt_id IN "
            "(SELECT id FROM prompts WHERE slug IN :prompt_slugs) "
            "OR agent_id IN (SELECT id FROM agents WHERE slug IN :agent_slugs)"
        ).bindparams(
            sa.bindparam("agent_slugs", expanding=True),
            sa.bindparam("prompt_slugs", expanding=True),
        ),
        parameters,
    )
    bind.execute(
        sa.text("DELETE FROM prompts WHERE slug IN :slugs")
        .bindparams(sa.bindparam("slugs", expanding=True)),
        {"slugs": tuple(_PROMPTS)},
    )
    # Versions/configuration cascade; prompt revision history stays detached.
    bind.execute(
        sa.text("DELETE FROM agents WHERE slug IN :slugs")
        .bindparams(sa.bindparam("slugs", expanding=True)),
        {"slugs": tuple(_AGENTS)},
    )


def downgrade() -> None:
    raise RuntimeError(
        "Retired Neri context is intentionally not recreated; "
        "restore the pre-cleanup Agent Hub snapshot if rollback is required."
    )
