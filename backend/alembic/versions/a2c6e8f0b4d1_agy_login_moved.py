"""agy's host login moved: Antigravity CLI 1.4 keeps it in antigravity-cli/antigravity-oauth-token.

The seeded row named ~/.gemini/oauth_creds.json, so a host that signed in still
read "needs sign-in". Only a row still at the seeded value changes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a2c6e8f0b4d1"
down_revision: str | Sequence[str] | None = "3f9e78fe4285"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE remote_tool_credentials SET auth_file = 'antigravity-cli/antigravity-oauth-token' "
        "WHERE tool_slug = 'agy' AND name = 'google-oauth' AND auth_file = 'oauth_creds.json'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE remote_tool_credentials SET auth_file = 'oauth_creds.json' "
        "WHERE tool_slug = 'agy' AND name = 'google-oauth' AND auth_file = 'antigravity-cli/antigravity-oauth-token'"
    )
