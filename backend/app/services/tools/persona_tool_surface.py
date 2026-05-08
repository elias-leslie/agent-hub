"""Canonical persona runtime tool surface.

Project permissions own the allow-list. This module keeps Jenny's provider
tool surface in sync with that project-visible set, while preserving stable
ordering for prompts and tests.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

PersonaToolTier = Literal["off", "read", "full"]

PERSONA_TOOL_TIERS: tuple[PersonaToolTier, ...] = ("off", "read", "full")

PERSONA_RUNTIME_TOOL_ORDER: tuple[str, ...] = (
    "bash",
    "read_file",
    "edit_file",
    "write_file",
    "search_scratch_context",
)


def normalize_persona_tool_tier(tier: str | None) -> PersonaToolTier:
    """Normalize permission tier labels, failing closed for persona surfaces."""
    from app.models.project_permission import normalize_permission_tier

    canonical_tier = normalize_permission_tier(tier)
    if canonical_tier is None:
        return "off"
    return canonical_tier  # type: ignore[return-value]


def infer_persona_tool_tier_from_visible_tools(
    visible_tool_names: Iterable[str] | None,
) -> PersonaToolTier:
    """Infer a coarse tier from an already-resolved project-visible set."""
    if not visible_tool_names:
        return "off"
    visible = set(visible_tool_names)
    if "bash" in visible:
        return "full"
    if "read_file" in visible:
        return "read"
    return "off"


def get_persona_runtime_tools_for_tier(tier: str | None) -> tuple[str, ...]:
    """Return ordered hot-loaded runtime tool ids for a persona permission tier."""
    if normalize_persona_tool_tier(tier) == "off":
        return ()
    from app.services.project_permission_service import get_visible_tools_for_tier

    return _ordered_persona_runtime_tools(
        get_visible_tools_for_tier(normalize_persona_tool_tier(tier))
    )


def get_persona_runtime_tools_for_visible_tools(
    visible_tool_names: Iterable[str] | None,
) -> tuple[str, ...]:
    """Return ordered hot-loaded runtime tool ids from project-visible tool ids."""
    return _ordered_persona_runtime_tools(visible_tool_names)


def get_persona_operator_tools_for_tier(tier: str | None) -> tuple[str, ...]:
    """Return ordered operator-facing tool names for a persona permission tier."""
    return get_persona_runtime_tools_for_tier(tier)


def get_persona_operator_tools_for_visible_tools(
    visible_tool_names: Iterable[str] | None,
) -> tuple[str, ...]:
    """Return ordered operator-facing tool names from project-visible tool ids."""
    return get_persona_runtime_tools_for_visible_tools(visible_tool_names)


def format_persona_operator_tools_for_tier(tier: str | None) -> str:
    """Return the compact operator-facing list used in permission text."""
    tools = get_persona_operator_tools_for_tier(tier)
    return ", ".join(tools) if tools else "none"


def filter_persona_runtime_tool_dicts(
    tools: Sequence[dict[str, object]],
    *,
    visible_tool_names: Iterable[str] | None,
) -> list[dict[str, object]]:
    """Keep only tools allowed in Jenny's project-visible runtime surface."""
    by_name = {str(tool.get("name", "") or ""): tool for tool in tools}
    return [
        by_name[name]
        for name in get_persona_runtime_tools_for_visible_tools(visible_tool_names)
        if name in by_name
    ]


def _ordered_persona_runtime_tools(
    visible_tool_names: Iterable[str] | None,
) -> tuple[str, ...]:
    if not visible_tool_names:
        return ()
    visible = set(visible_tool_names)
    return tuple(name for name in PERSONA_RUNTIME_TOOL_ORDER if name in visible)
