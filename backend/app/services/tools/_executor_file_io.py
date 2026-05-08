"""File I/O operations for direct tool executor.

Handles reading and writing files with path boundary enforcement
and proper error reporting.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

logger = logging.getLogger(__name__)

LARGE_OVERWRITE_MIN_BYTES = 16_000
LARGE_OVERWRITE_MIN_RATIO = 0.7


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

    if not _is_path_allowed(file_path, allowed_root, extra_roots=(working_dir,)):
        return f"Error: Path outside allowed project root: {path}"

    if not file_path.exists():
        return f"Error: File not found: {path}"
    if file_path.is_dir():
        return f"Error: Path is a directory: {path}"

    def _read() -> str:
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

    try:
        return await asyncio.to_thread(_read)
    except Exception as e:
        return f"Error reading file: {e}"


async def write_file(
    path: str,
    content: str,
    working_dir: Path,
    allowed_root: Path | None,
    *,
    allow_large_truncate: bool = False,
) -> str:
    """Write a file, creating parent directories as needed."""
    file_path = _resolve_path(path, working_dir)

    if not _is_path_allowed(file_path, allowed_root, extra_roots=(working_dir,)):
        return f"Error: Path outside allowed project root: {path}"

    def _write() -> str:
        if file_path.exists() and file_path.is_file() and not allow_large_truncate:
            original_size = file_path.stat().st_size
            new_size = len(content.encode("utf-8"))
            if (
                original_size >= LARGE_OVERWRITE_MIN_BYTES
                and new_size < original_size * LARGE_OVERWRITE_MIN_RATIO
            ):
                return (
                    "Error: Refusing large destructive overwrite of existing file "
                    f"{path}: {original_size} bytes -> {new_size} bytes. "
                    "Use edit_file for targeted changes, or pass allow_large_truncate=true "
                    "only after intentionally replacing the whole file."
                )
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {len(content)} bytes to {path}"

    try:
        return await asyncio.to_thread(_write)
    except Exception as e:
        return f"Error writing file: {e}"


async def edit_file(
    path: str,
    old_text: str,
    new_text: str,
    working_dir: Path,
    allowed_root: Path | None,
    *,
    replace_all: bool = False,
    content_guard: Callable[[str], Awaitable[str | None]] | None = None,
) -> str:
    """Edit an existing file by replacing exact text."""
    file_path = _resolve_path(path, working_dir)

    if not _is_path_allowed(file_path, allowed_root, extra_roots=(working_dir,)):
        return f"Error: Path outside allowed project root: {path}"
    if not old_text:
        return "Error: old_text must be non-empty"

    def _prepare() -> tuple[str, int, int] | str:
        if not file_path.exists():
            return f"Error: File not found: {path}"
        if file_path.is_dir():
            return f"Error: Path is a directory: {path}"

        current = file_path.read_text(encoding="utf-8", errors="replace")
        match_count = current.count(old_text)
        if match_count == 0:
            return f"Error: old_text not found in {path}"
        if match_count > 1 and not replace_all:
            return (
                f"Error: old_text matched {match_count} times in {path}; "
                "provide more surrounding context or pass replace_all=true."
            )
        replacements = match_count if replace_all else 1
        updated = current.replace(old_text, new_text, replacements)
        return updated, replacements, len(current)

    try:
        prepared = await asyncio.to_thread(_prepare)
        if isinstance(prepared, str):
            return prepared
        updated, replacements, original_len = prepared
        if content_guard:
            block_reason = await content_guard(updated)
            if block_reason:
                return f"Error: Edit blocked: {block_reason}"

        def _write() -> str:
            file_path.write_text(updated, encoding="utf-8")
            return (
                f"Successfully edited {path}: replaced {replacements} occurrence(s), "
                f"{original_len} bytes -> {len(updated)} bytes"
            )

        return await asyncio.to_thread(_write)
    except Exception as e:
        return f"Error editing file: {e}"


def _is_path_allowed(
    path: Path,
    allowed_root: Path | None,
    extra_roots: tuple[Path, ...] = (),
) -> bool:
    """Check if a resolved path is within the allowed root or extra roots.

    Extra roots support alternate checkout paths: when an agent executes from a
    task-specific checkout root, the working_dir may sit outside allowed_root
    but should still be allowed.
    """
    if not allowed_root:
        return True
    resolved = path.resolve()
    for root in (allowed_root, *extra_roots):
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False
