"""Remember where in the answer each tool call happened.

A chat turn stores its answer as one text, so the text between tool calls ("I will fix these files." ...
"Fixed: ...") ran together when the chat was reopened. A tool-call event now carries how much of the answer
had streamed when the call started (UTF-16 units, the way the browser counts), so a reopened chat puts each
call where it happened. NULL on every earlier event: those turns keep showing their calls before the text.
"""

import sqlalchemy as sa

from alembic import op

revision = "a7d2e9c4b1f3"
down_revision = "f4c8a2d6b1e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("session_events", sa.Column("content_offset", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("session_events", "content_offset")
