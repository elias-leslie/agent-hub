"""Pre-write secret check for DirectExecutor write_file and edit_file.

Uses the same high-confidence floor that redacts stored history
(``secret_redaction``). It runs in process, so there is no scanner that can go
missing, and no repo allowlist or inline marker can silence it.
"""

from __future__ import annotations

from app.services.secret_redaction import redact_secrets


def secret_block_reason(path: str, content: str) -> str | None:
    """Return a block reason when ``content`` holds a credential, else None."""
    if not content:
        return None
    _, counts = redact_secrets(content)
    if not counts:
        return None
    kinds = ", ".join(kind.replace("_", " ") for kind in counts)
    return f"content contains a credential ({kinds}) ({path})"
