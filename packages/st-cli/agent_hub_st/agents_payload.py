"""Payload builders for the Agent Hub agents CLI."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def build_agent_payload(
    *,
    name: str | None,
    description: str | None,
    primary_model: str | None,
    escalation_model: str | None,
    temperature: float | None,
    timeout_seconds: float | None,
    thinking_level: str | None,
    active: bool | None,
    coding_agent: bool | None,
    fallback_model: list[str] | None,
    change_reason: str | None,
    system_prompt_file: Path | None,
    load_text_file: Callable[[Path, str], str],
) -> dict[str, Any]:
    """Build the base update payload from scalar CLI flags."""
    payload: dict[str, Any] = {}
    for key, val in [
        ("name", name), ("description", description), ("primary_model_id", primary_model),
        ("escalation_model_id", escalation_model),
        ("temperature", temperature), ("timeout_seconds", timeout_seconds), ("thinking_level", thinking_level),
        ("is_active", active), ("is_coding_agent", coding_agent),
        ("fallback_models", fallback_model), ("change_reason", change_reason),
    ]:
        if val is not None:
            payload[key] = val
    if system_prompt_file is not None:
        payload["system_prompt"] = load_text_file(system_prompt_file, "System prompt")
    return payload
