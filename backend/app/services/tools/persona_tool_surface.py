"""Canonical persona operator tool surface.

Provider-native Claude built-ins stay owned by the adapter constants. This
module owns only the persona hot-loaded runtime tools and their operator-facing
display names.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

PersonaToolTier = Literal["off", "read", "write", "yolo"]

PERSONA_TOOL_TIERS: tuple[PersonaToolTier, ...] = ("off", "read", "write", "yolo")

PERSONA_RUNTIME_TOOLS_BY_TIER: dict[PersonaToolTier, tuple[str, ...]] = {
    "off": (),
    "read": ("read_file",),
    "write": ("read_file", "write_file"),
    "yolo": ("bash", "read_file", "write_file"),
}

PERSONA_OPERATOR_TOOLS_BY_TIER: dict[PersonaToolTier, tuple[str, ...]] = {
    "off": (),
    "read": ("Read",),
    "write": ("Read", "Write", "Edit"),
    "yolo": ("Read", "Write", "Edit", "Bash"),
}


def normalize_persona_tool_tier(tier: str | None) -> PersonaToolTier:
    """Normalize permission tier labels, failing closed for persona surfaces."""
    if tier is None:
        return "off"
    normalized = tier.strip().lower()
    if normalized in PERSONA_TOOL_TIERS:
        return normalized  # type: ignore[return-value]
    return "off"


def infer_persona_tool_tier_from_visible_tools(
    visible_tool_names: Iterable[str] | None,
) -> PersonaToolTier:
    """Infer the fixed persona tier from an already-resolved project-visible set."""
    if not visible_tool_names:
        return "off"
    visible = set(visible_tool_names)
    if "bash" in visible:
        return "yolo"
    if "write_file" in visible:
        return "write"
    if "read_file" in visible:
        return "read"
    return "off"


def get_persona_runtime_tools_for_tier(tier: str | None) -> tuple[str, ...]:
    """Return ordered hot-loaded runtime tool ids for a persona permission tier."""
    return PERSONA_RUNTIME_TOOLS_BY_TIER[normalize_persona_tool_tier(tier)]


def get_persona_runtime_tools_for_visible_tools(
    visible_tool_names: Iterable[str] | None,
) -> tuple[str, ...]:
    """Return ordered hot-loaded runtime tool ids from project-visible tool ids."""
    return PERSONA_RUNTIME_TOOLS_BY_TIER[
        infer_persona_tool_tier_from_visible_tools(visible_tool_names)
    ]


def get_persona_operator_tools_for_tier(tier: str | None) -> tuple[str, ...]:
    """Return ordered operator-facing tool names for a persona permission tier."""
    return PERSONA_OPERATOR_TOOLS_BY_TIER[normalize_persona_tool_tier(tier)]


def get_persona_operator_tools_for_visible_tools(
    visible_tool_names: Iterable[str] | None,
) -> tuple[str, ...]:
    """Return ordered operator-facing tool names from project-visible tool ids."""
    return PERSONA_OPERATOR_TOOLS_BY_TIER[
        infer_persona_tool_tier_from_visible_tools(visible_tool_names)
    ]


def format_persona_operator_tools_for_tier(tier: str | None) -> str:
    """Return the compact operator-facing list used in permission text."""
    tools = get_persona_operator_tools_for_tier(tier)
    return ", ".join(tools) if tools else "none"


def filter_persona_runtime_tool_dicts(
    tools: Sequence[dict[str, object]],
    *,
    visible_tool_names: Iterable[str] | None,
) -> list[dict[str, object]]:
    """Keep only tools allowed in the fixed persona runtime surface."""
    allowed = set(get_persona_runtime_tools_for_visible_tools(visible_tool_names))
    return [tool for tool in tools if str(tool.get("name", "") or "") in allowed]
