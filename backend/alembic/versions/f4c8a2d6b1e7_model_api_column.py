"""Add the per-model wire API to the model catalog.

A provider can serve different models through different APIs (OpenCode Go serves its Qwen models on an
Anthropic-style endpoint and DeepSeek, GLM and MiMo on an OpenAI-style one). The catalog row now says which;
NULL keeps the provider's own API, so every existing row is unchanged.
"""

import sqlalchemy as sa

from alembic import op

revision = "f4c8a2d6b1e7"
down_revision = "e3b7c1a9d5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("models", sa.Column("api", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("models", "api")
