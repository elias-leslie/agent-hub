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

    if "enabled" in memory_config:
        settings.enabled = memory_config["enabled"]
    elif "injection_enabled" in memory_config:
        settings.enabled = memory_config["injection_enabled"]
