"""Centralized tool registry loader.

Reads tool-registry.json (single source of truth for tool enforcement)
and provides compiled regex patterns for command redirect checking.

Used by direct_executor_core.py for Gemini/future adapters.
Same registry is read by PreToolUse.sh (Claude hooks) and dt (dev-tools.sh).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, cast

from app.core.project_roots import resolve_summitflow_scripts_dir

logger = logging.getLogger(__name__)

# Module-level cache (loaded once at first use)
_cached_registry: dict[str, Any] | None = None
_cached_patterns: list[tuple[re.Pattern[str], str]] | None = None
_cached_wrapper_pattern: re.Pattern[str] | None = None


def _load_registry(path: Path | None = None) -> dict[str, Any] | None:
    """Load and parse the tool registry JSON file.

    Args:
        path: Override path for testing. Defaults to REGISTRY_PATH.

    Returns:
        Parsed registry dict, or None if file missing/invalid.
    """
    target = path
    if target is None:
        scripts_dir = resolve_summitflow_scripts_dir()
        if scripts_dir is None:
            logger.warning("Shared SummitFlow scripts root is unavailable; tool redirects disabled")
            return None
        target = scripts_dir / "lib" / "tool-registry.json"
    try:
        if not target.exists():
            logger.warning("Tool registry not found: %s", target)
            return None
        with open(target, encoding="utf-8") as f:
            return cast(dict[str, Any], json.load(f))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load tool registry: %s", e)
        return None


def _build_redirect_patterns(
    registry: dict[str, Any],
) -> list[tuple[re.Pattern[str], str]]:
    """Build compiled regex patterns from registry data.

    Combines tool redirect patterns and service redirect patterns into
    a single list of (compiled_regex, message) tuples.

    Args:
        registry: Parsed registry dict.

    Returns:
        List of (pattern, redirect_message) tuples.
    """
    cmd_start = registry.get("cmd_start", "(^|&&\\s*|;\\s*)")
    patterns: list[tuple[re.Pattern[str], str]] = []

    # Tool redirect patterns
    for tool in registry.get("tools", []):
        message = tool.get("redirect_message", "")
        for pat in tool.get("redirect_patterns", []):
            full_pattern = cmd_start + pat
            patterns.append((re.compile(full_pattern), message))

    # Service redirect patterns
    for svc in registry.get("service_redirects", []):
        pat = svc.get("pattern", "")
        message = svc.get("message", "")
        full_pattern = cmd_start + pat
        patterns.append((re.compile(full_pattern), message))

    return patterns


def _build_wrapper_pattern(registry: dict[str, Any]) -> re.Pattern[str] | None:
    """Build compiled regex for wrapper allowlist.

    Commands matching this pattern are wrappers (dt, st, etc.) and
    should bypass all redirect checks.

    Args:
        registry: Parsed registry dict.

    Returns:
        Compiled regex pattern, or None if no allowlist.
    """
    allowlist = registry.get("wrapper_allowlist", [])
    if not allowlist:
        return None
    cmd_start = registry.get("cmd_start", "(^|&&\\s*|;\\s*)")
    combined = "|".join(allowlist)
    return re.compile(cmd_start + f"({combined})")


def get_registry() -> dict[str, Any] | None:
    """Get the parsed tool registry (cached after first load).

    Returns:
        Registry dict, or None if unavailable.
    """
    global _cached_registry
    if _cached_registry is None:
        _cached_registry = _load_registry()
    return _cached_registry


def get_command_redirect(command: str) -> str | None:
    """Check if a command should be redirected to a standardized wrapper.

    Loads and caches the registry on first call. Returns redirect message
    if command matches a blocked pattern, None if allowed.

    Args:
        command: The shell command string to check.

    Returns:
        Redirect message string if command should be blocked, None if allowed.
    """
    global _cached_patterns, _cached_wrapper_pattern, _cached_registry

    # Load registry if needed
    if _cached_registry is None:
        _cached_registry = _load_registry()
        if _cached_registry is None:
            return None  # No registry = allow all

    # Build patterns if needed
    if _cached_patterns is None:
        _cached_patterns = _build_redirect_patterns(_cached_registry)
        _cached_wrapper_pattern = _build_wrapper_pattern(_cached_registry)

    # Allow if command uses a wrapper
    if _cached_wrapper_pattern and _cached_wrapper_pattern.search(command):
        return None

    # Check redirect patterns
    for pattern, message in _cached_patterns:
        if pattern.search(command):
            return message

    return None
