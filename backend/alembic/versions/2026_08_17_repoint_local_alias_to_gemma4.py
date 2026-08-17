"""repoint the bare `local` alias at the model that is actually installed

Revision ID: d4f1a8c62e97
Revises: a7b8c9d0e1f2
Create Date: 2026-08-17 18:35:00.000000

``seed_alias_overrides()`` only writes aliases on first boot, so correcting the
constant is not enough — the stored row has to move too.

``local`` pointed at ``local/qwen3-coder:30b-a3b``, a tag that returns HTTP 404
from the Ollama registry and has never been installed. Anything resolving the
bare provider name ``local`` therefore resolved to a model that cannot answer.
``local/gemma4:12b-it-qat`` is pulled, resident at 100% GPU, and verified for
tool calling and vision.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4f1a8c62e97"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_TARGET = "local/qwen3-coder:30b-a3b"
NEW_TARGET = "local/gemma4:12b-it-qat"


def _repoint(target: str, expected_current: str) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE model_aliases SET model_id = :target, updated_at = now() "
            "WHERE alias = 'local' AND model_id = :expected"
        ),
        {"target": target, "expected": expected_current},
    )


def upgrade() -> None:
    _repoint(NEW_TARGET, OLD_TARGET)


def downgrade() -> None:
    _repoint(OLD_TARGET, NEW_TARGET)
