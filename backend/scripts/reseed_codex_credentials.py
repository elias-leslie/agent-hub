"""Re-seed Codex OAuth credentials from the local Codex CLI's token file.

Agent Hub and the Codex CLI authenticate against the *same* OAuth grant, and
OpenAI's refresh tokens are single-use: whichever party refreshes last
invalidates the other's stored copy. When the CLI refreshes, Agent Hub's stored
refresh token starts returning ``refresh_token_invalidated`` and every routed
Codex call fails -- silently, as an empty 200, because the provider swallows the
auth error. This copies the CLI's live tokens back into the credential store so
service resumes without a browser login.

It is a repair, not a fix: the next CLI refresh breaks it again. The durable fix
is a separate OAuth grant for Agent Hub (wiki: codex-oauth-token-rotation).

Never prints a token value. Run from ``backend/``:
    uv run python scripts/reseed_codex_credentials.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.adapters.codex_auth import extract_account_id, extract_expires_at
from app.db import _get_session_factory
from app.services.credential_manager import get_credential_manager
from app.services.credential_upsert import upsert_credential

AUTH_FILE = Path.home() / ".codex" / "auth.json"


def read_cli_tokens() -> tuple[str, str, float | None]:
    """Return (access_token, refresh_token, expires_at) from the CLI's auth file."""
    if not AUTH_FILE.exists():
        raise SystemExit(f"no Codex CLI token file at {AUTH_FILE}; run `codex login` first")

    data = json.loads(AUTH_FILE.read_text())
    tokens = data.get("tokens") or {}
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not access_token or not refresh_token:
        raise SystemExit(f"{AUTH_FILE} has no access/refresh token pair")

    return access_token, refresh_token, extract_expires_at(access_token)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="report what would be written")
    args = parser.parse_args()

    access_token, refresh_token, expires_at = read_cli_tokens()
    account_id = extract_account_id(access_token)
    expiry = datetime.fromtimestamp(expires_at, tz=UTC).isoformat() if expires_at else "unknown"
    remaining = (expires_at - datetime.now(tz=UTC).timestamp()) / 3600 if expires_at else 0.0

    print(f"source:  {AUTH_FILE}")
    print(f"account: {account_id}")
    print(f"expires: {expiry} ({remaining:.0f}h remaining)")

    if remaining <= 0:
        print("refusing: the CLI's own access token has already expired")
        return 1

    payload: dict[str, object] = {"access_token": access_token}
    if expires_at is not None:
        payload["expires_at"] = expires_at
    token_value = json.dumps(payload)

    if args.dry_run:
        print("dry-run: would upsert codex/oauth_token and codex/refresh_token")
        return 0

    factory = _get_session_factory()
    async with factory() as db:
        cm = get_credential_manager()
        await cm.load(db)
        await upsert_credential(db, "codex", "oauth_token", token_value)
        await upsert_credential(db, "codex", "refresh_token", refresh_token)
        await db.commit()

    print("wrote: codex/oauth_token, codex/refresh_token")
    print("restart the backend so the running process reloads its credential cache")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
