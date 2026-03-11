"""Precision Code Search tool executor."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_PRECISION_SEARCH_BUDGET = 1200
PRECISION_SEARCH_SCRIPT = Path("/home/kasadis/summitflow/scripts/precision-code-search.py")


def _error_payload(message: str, **extra: object) -> str:
    payload: dict[str, object] = {"error": message, **extra}
    return json.dumps(payload, indent=2, sort_keys=True)


async def precision_code_search(
    query: str,
    project_id: str | None,
    budget: int = DEFAULT_PRECISION_SEARCH_BUDGET,
) -> str:
    """Run Precision Code Search through SummitFlow's shared CLI."""
    normalized_query = query.strip()
    if not normalized_query:
        return _error_payload("precision_code_search requires a non-empty query")
    if not project_id:
        return _error_payload("precision_code_search requires a project_id context")
    if budget <= 0:
        return _error_payload("precision_code_search budget must be positive")
    if not PRECISION_SEARCH_SCRIPT.exists():
        return _error_payload(
            "precision_code_search script is unavailable",
            script=str(PRECISION_SEARCH_SCRIPT),
        )

    cmd = [
        sys.executable,
        str(PRECISION_SEARCH_SCRIPT),
        "search",
        "--project",
        project_id,
        "--budget",
        str(budget),
        "--json",
        normalized_query,
    ]
    completed = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return _error_payload(
            "precision_code_search command failed",
            returncode=completed.returncode,
            stderr=completed.stderr.strip(),
            stdout=completed.stdout.strip(),
        )

    stdout = completed.stdout.strip()
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return _error_payload(
            "precision_code_search returned invalid JSON",
            stdout=stdout,
        )

    return json.dumps(payload, indent=2, sort_keys=True)


__all__ = [
    "DEFAULT_PRECISION_SEARCH_BUDGET",
    "PRECISION_SEARCH_SCRIPT",
    "precision_code_search",
]
