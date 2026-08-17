"""deactivate models verified unreachable in 2026-08 liveness sweep

Revision ID: a7b8c9d0e1f2
Revises: 7f4e2d1c9b8a
Create Date: 2026-08-17 18:05:00.000000

``seed_model_catalog()`` inserts missing rows but never overwrites existing DB
values, so removing an entry from the seed constants cannot retire a row that is
already present. Deactivation has to happen here.

Each id below was probed directly:

- ``nvidia/qwen3.5-397b-a17b``     HTTP 410 Gone (NIM EOL 2026-07-27)
- ``nvidia/kimi-k2.6``             HTTP 404 function not found
- ``gemini-3.1-flash-lite-preview`` preview endpoint retired upstream
- ``local/qwen3-coder:30b-a3b``    HTTP 404 in the Ollama registry — the tag has
  never existed; ``qwen3-coder`` only publishes ``:latest`` (18.6 GB)
- ``local/qwen3:30b-a3b``          exists upstream but is not installed, and at
  ~18 GB q4 does not fit the 16 GB RTX 4080 SUPER alongside the resident model
- ``local/qwen2.5-coder:14b``      exists upstream but is not installed

``local/gemma4:12b-it-qat`` is deliberately left active: it is pulled, resident
at 100% GPU (8.0 GB at 32k context), and verified for both tool calling and
vision, and it is the terminal fallback rung for 75 agents.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "7f4e2d1c9b8a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (model id, availability note recorded on the row)
DEACTIVATED: list[tuple[str, str]] = [
    ("nvidia/qwen3.5-397b-a17b", "retired_2026-08-17; nim_eol_2026-07-27_http_410"),
    ("nvidia/kimi-k2.6", "retired_2026-08-17; nim_http_404_function_not_found"),
    ("gemini-3.1-flash-lite-preview", "retired_2026-08-17; preview_endpoint_removed_upstream"),
    ("local/qwen3-coder:30b-a3b", "retired_2026-08-17; ollama_tag_does_not_exist_http_404"),
    ("local/qwen3:30b-a3b", "retired_2026-08-17; not_installed_exceeds_16gb_vram_budget"),
    ("local/qwen2.5-coder:14b", "retired_2026-08-17; not_installed"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for model_id, availability in DEACTIVATED:
        conn.execute(
            sa.text(
                "UPDATE models SET is_active = false, availability = :availability, "
                "updated_at = now() WHERE id = :id"
            ),
            {"id": model_id, "availability": availability},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for model_id, _ in DEACTIVATED:
        conn.execute(
            sa.text("UPDATE models SET is_active = true, updated_at = now() WHERE id = :id"),
            {"id": model_id},
        )
