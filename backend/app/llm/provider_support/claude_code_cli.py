"""Host support for the headless Claude Code CLI provider.

Kept outside ``providers`` so routing can ask whether the CLI is usable
without importing a provider module (D8).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time

from app.utils.safe_subprocess import create_process

_AUTH_STATUS_TTL_S = 60.0
# Session variables of an enclosing Claude Code process must not leak into the
# isolated child, which would otherwise attach to the parent's session.
_PASSTHROUGH_ENV = ("HOME", "PATH", "LANG", "LC_ALL", "TZ", "XDG_CONFIG_HOME", "XDG_DATA_HOME")

_auth_status: tuple[float, bool] | None = None


def claude_binary() -> str | None:
    """Return the ``claude`` executable on PATH, if installed."""
    return shutil.which("claude")


def child_env() -> dict[str, str]:
    """Return the minimal environment for an isolated CLI child."""
    env = {key: os.environ[key] for key in _PASSTHROUGH_ENV if key in os.environ}
    env.setdefault("LANG", "C.UTF-8")
    env["DISABLE_AUTOUPDATER"] = "1"
    return env


async def claude_cli_signed_in() -> bool:
    """Return whether the CLI reports a signed-in account.

    ``claude auth status`` reads the CLI's local login state; it makes no
    model call and spends no tokens. Results are cached briefly.
    """
    global _auth_status
    now = time.monotonic()
    if _auth_status is not None and now - _auth_status[0] < _AUTH_STATUS_TTL_S:
        return _auth_status[1]
    binary = claude_binary()
    signed_in = False
    if binary:
        try:
            process = await create_process(
                binary, "auth", "status", env=child_env(), stderr=asyncio.subprocess.DEVNULL
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=15)
            signed_in = bool(json.loads(stdout or b"{}").get("loggedIn"))
        except (OSError, TimeoutError, ValueError):
            signed_in = False
    _auth_status = (now, signed_in)
    return signed_in
