"""Runtime sensitive-content scanning for pre-write enforcement."""

from __future__ import annotations

import asyncio
import json
import logging

from app.core.project_roots import resolve_summitflow_scripts_dir
from app.utils.safe_subprocess import create_process

logger = logging.getLogger(__name__)
_DEFAULT_BLOCK_REASON = "sensitive content requires review"


def _parse_scan_output(stdout: bytes, stderr: bytes, path: str) -> str:
    """Extract a human-readable block reason from scanner output."""
    payload_text = stdout.decode("utf-8", errors="replace").strip()
    if payload_text:
        try:
            payload = json.loads(payload_text)
            findings = payload.get("findings") or []
            if findings:
                first = findings[0]
                description = str(first.get("description") or _DEFAULT_BLOCK_REASON)
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

    return _DEFAULT_BLOCK_REASON


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

    scripts_dir = resolve_summitflow_scripts_dir()
    if scripts_dir is None:
        logger.warning("Shared SummitFlow scripts root is unavailable; skipping runtime scan")
        return None

    scanner = scripts_dir / "lib" / "sensitive_scan.py"
    if not scanner.exists():
        logger.warning("Sensitive-content scanner missing at %s; skipping runtime scan", scanner)
        return None

    cmd = ["python3", str(scanner), "--mode", "runtime", "--json", "--path", path]
    if repo_root:
        cmd.extend(["--repo-root", repo_root])
    if tool_name:
        cmd.extend(["--tool-name", tool_name])
    cmd.extend(["--content-file", "-"])

    try:
        process = await create_process(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(content.encode("utf-8"))
    except Exception as exc:
        logger.warning("Runtime sensitive-content scan failed to execute: %s", exc)
        return None

    if process.returncode == 0:
        return None

    return _parse_scan_output(stdout, stderr, path)
