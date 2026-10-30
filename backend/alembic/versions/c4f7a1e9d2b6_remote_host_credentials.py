"""Remote hosts and the per-tool credential map they launch with.

Hosts authenticate with their own bearer token (hash only). The tool map rows
are data: which credential each Tether tool uses, how it is delivered and
whether the login rotates. Rotating logins (Codex CLI, Pi OAuth, agy until its
refresh token is shown not to rotate) are signed in on the host and never served.
"""

import sqlalchemy as sa

from alembic import op

revision = "c4f7a1e9d2b6"
down_revision = "b8e3c5a7d9f2"
branch_labels = None
depends_on = None

_TOOL_MAP = [
    ("claude-code", "oauth-token", "claude", "~/.claude", "CLAUDE_CODE_OAUTH_TOKEN", None, False,
     "Long-lived token from `claude setup-token`, run on the host."),
    ("pi", "opencode-go", "pi", "~/.pi/agent", "OPENCODE_API_KEY", None, False,
     "OpenCode Go API key."),
    ("pi", "minimax", "pi", "~/.pi/agent", "MINIMAX_API_KEY", None, False,
     "MiniMax API key."),
    ("pi", "oauth", "pi", "~/.pi/agent", None, "auth.json", True,
     "Pi /login OAuth entries; signed in on the host."),
    ("codex", "login", "codex", "~/.codex", None, "auth.json", True,
     "Codex CLI login (`codex login --device-auth`); signed in on the host."),
    ("agy", "google-oauth", "agy", "~/.gemini", None, "oauth_creds.json", True,
     "Google login; treated as rotating until its refresh token is shown not to rotate."),
]


def upgrade() -> None:
    op.create_table(
        "remote_hosts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("granted_tools", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    table = op.create_table(
        "remote_tool_credentials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tool_slug", sa.String(50), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("command", sa.String(50), nullable=False),
        sa.Column("config_dir", sa.String(200), nullable=False),
        sa.Column("env_var", sa.String(100), nullable=True),
        sa.Column("auth_file", sa.String(200), nullable=True),
        sa.Column("rotates", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tool_slug", "name", name="uq_remote_tool_credentials_tool_name"),
        sa.CheckConstraint("(env_var IS NULL) <> (auth_file IS NULL)", name="ck_remote_tool_credentials_one_delivery"),
    )
    op.bulk_insert(table, [
        {"tool_slug": tool, "name": name, "command": command, "config_dir": config_dir, "env_var": env_var,
         "auth_file": auth_file, "rotates": rotates, "description": description}
        for tool, name, command, config_dir, env_var, auth_file, rotates, description in _TOOL_MAP
    ])


def downgrade() -> None:
    op.execute("DELETE FROM credentials WHERE provider LIKE '\\_host\\_tool\\_%'")
    op.drop_table("remote_tool_credentials")
    op.drop_table("remote_hosts")
