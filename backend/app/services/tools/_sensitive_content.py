"""Runtime sensitive-content scanning for pre-write enforcement."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_SCANNER = Path.home() / "summitflow" / "scripts" / "lib" / "sensitive_scan.py"


async def scan_runtime_sensitive_content(
    path: str,
    content: str,
    *,
    repo_root: str | None = None,
    tool_name: str | None = None,
) -> str | None:
    """Return a block reason when content should not be written."""
    if not path and not content:
        return None

    if not _SCANNER.exists():
        logger.warning("Sensitive-content scanner missing at %s; skipping runtime scan", _SCANNER)
        return None

    cmd = ["python3", str(_SCANNER), "--mode", "runtime", "--json", "--path", path]
    if repo_root:
        cmd.extend(["--repo-root", repo_root])
    if tool_name:
        cmd.extend(["--tool-name", tool_name])
    cmd.extend(["--content-file", "-"])

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(content.encode("utf-8"))
    except Exception as exc:
        logger.warning("Runtime sensitive-content scan failed to execute: %s", exc)
        return None

    if process.returncode == 0:
        return None

    payload_text = stdout.decode("utf-8", errors="replace").strip()
    if payload_text:
        try:
            payload = json.loads(payload_text)
            findings = payload.get("findings") or []
            if findings:
                first = findings[0]
                description = str(first.get("description") or "sensitive content requires review")
                finding_path = str(first.get("path") or path)
                return f"{description} ({finding_path})"
            summary = str(payload.get("summary") or "").strip()
            if summary:
                return summary
        except json.JSONDecodeError:
            pass

    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if stderr_text:
        return stderr_text.splitlines()[0]

    return "sensitive content requires review"
