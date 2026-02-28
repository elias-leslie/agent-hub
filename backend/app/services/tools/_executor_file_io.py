"""File I/O operations for direct tool executor.

Handles reading and writing files with path boundary enforcement
and proper error reporting.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_path(path: str, working_dir: Path) -> Path:
    """Resolve a path, making relative paths absolute from working_dir."""
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = (working_dir / path).resolve()
    return file_path


async def read_file(
    path: str,
    working_dir: Path,
    allowed_root: Path | None,
    offset: int = 0,
    limit: int = 2000,
) -> str:
    """Read a file with optional line offset and limit."""
    file_path = _resolve_path(path, working_dir)

    if not _is_path_allowed(file_path, allowed_root):
        return f"Error: Path outside allowed project root: {path}"

    if not file_path.exists():
        return f"Error: File not found: {path}"
    if file_path.is_dir():
        return f"Error: Path is a directory: {path}"

    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        selected = lines[offset : offset + limit]

        result_lines = [
            f"{i:6}\t{line.rstrip()}"
            for i, line in enumerate(selected, start=offset + 1)
        ]

        result = "\n".join(result_lines)

        if offset + limit < total_lines:
            result += f"\n... ({total_lines - offset - limit} more lines)"

        return result or "(empty file)"

    except Exception as e:
        return f"Error reading file: {e}"


async def write_file(
    path: str,
    content: str,
    working_dir: Path,
    allowed_root: Path | None,
) -> str:
    """Write a file, creating parent directories as needed."""
    file_path = _resolve_path(path, working_dir)

    if not _is_path_allowed(file_path, allowed_root):
        return f"Error: Path outside allowed project root: {path}"

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def _is_path_allowed(path: Path, allowed_root: Path | None) -> bool:
    """Check if a resolved path is within the allowed root."""
    if not allowed_root:
        return True
    try:
        path.resolve().relative_to(allowed_root)
        return True
    except ValueError:
        return False
