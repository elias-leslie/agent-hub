"""File-based token cache for Codex OAuth credentials.

Provides cross-process safe token caching using file locks to coordinate
token refresh across concurrent worker processes.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

from filelock import FileLock

from app.adapters.codex_auth import CodexCredentials, extract_account_id

# File-based lock for coordinating token refresh across concurrent workers
_TOKEN_LOCK_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
_TOKEN_LOCK_PATH = _TOKEN_LOCK_DIR / "agent-hub-codex-token.lock"
_TOKEN_CACHE_PATH = _TOKEN_LOCK_DIR / "agent-hub-codex-token.json"

_CACHE_FRESHNESS_SECONDS = 30


def _secure_write(path: Path, data: str) -> None:
    """Write *data* to *path* with owner-only (0o600) permissions."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(data)


def read_cached_token(refresh_token: str) -> CodexCredentials | None:
    """Acquire file lock and return cached credentials if still fresh.

    Returns a CodexCredentials if the cache is fresh (within
    ``_CACHE_FRESHNESS_SECONDS``), else None.
    """
    lock = FileLock(str(_TOKEN_LOCK_PATH), timeout=10)
    with lock:
        if not _TOKEN_CACHE_PATH.exists():
            return None
        try:
            cached = json.loads(_TOKEN_CACHE_PATH.read_text())
            cached_at = cached.get("refreshed_at", 0)
            if time.time() - cached_at >= _CACHE_FRESHNESS_SECONDS:
                return None
            account_id = extract_account_id(cached["access_token"])
            return CodexCredentials(
                access_token=cached["access_token"],
                refresh_token=cached.get("refresh_token", refresh_token),
                account_id=account_id,
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            return None


def write_cached_token(new_creds: CodexCredentials) -> None:
    """Acquire file lock and write refreshed token to cache with secure permissions."""
    lock = FileLock(str(_TOKEN_LOCK_PATH), timeout=10)
    with lock, contextlib.suppress(OSError):
        _secure_write(
            _TOKEN_CACHE_PATH,
            json.dumps(
                {
                    "access_token": new_creds.access_token,
                    "refresh_token": new_creds.refresh_token,
                    "refreshed_at": time.time(),
                }
            ),
        )
