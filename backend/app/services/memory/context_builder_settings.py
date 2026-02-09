"""Settings override logic for progressive context."""

from __future__ import annotations

from typing import Any

from .settings import MemorySettingsDTO


def apply_memory_config_overrides(
    settings: MemorySettingsDTO,
    memory_config: dict[str, Any] | None,
) -> None:
    """Apply memory_config overrides to settings in-place.

    Args:
        settings: MemorySettingsDTO object to modify
        memory_config: Optional config dict from agent/request
    """
    if not memory_config:
        return

    mc_max_mandates = memory_config.get("max_mandates", 0)
    if mc_max_mandates > 0:
        settings.max_mandates = mc_max_mandates

    mc_max_guardrails = memory_config.get("max_guardrails", 0)
    if mc_max_guardrails > 0:
        settings.max_guardrails = mc_max_guardrails

    mc_total_budget = memory_config.get("total_budget", 0)
    if mc_total_budget > 0:
        settings.total_budget = mc_total_budget

    if "budget_enabled" in memory_config:
        settings.budget_enabled = memory_config["budget_enabled"]

    if "enabled" in memory_config:
        settings.enabled = memory_config["enabled"]
