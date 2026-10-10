"""Display helpers for the persona CLI."""

from __future__ import annotations

from typing import Any


def field_status(persona: dict[str, Any], field: str) -> str:
    val = persona.get(field)
    if not val:
        return "unset"
    return f"set ({len(val)} chars)" if isinstance(val, str) else "set"


def print_persona(persona: dict[str, Any]) -> None:
    preview = ""
    if persona.get("personality"):
        lines = persona["personality"].strip().splitlines()
        preview = lines[0][:60] if lines else ""
    print(f"persona | {persona.get('name', '?')} | agent={persona.get('agent_slug', '?')}")
    print(f"  voice={persona.get('voice_id', '?')} enabled={persona.get('voice_enabled', False)}")
    print(f"  heartbeat={persona.get('heartbeat_interval_minutes', 0)}m")
    mode = persona.get("session_reset_mode", "off")
    if mode == "daily":
        detail = f" hour={persona.get('session_reset_hour', 0)}"
    elif mode == "idle":
        detail = f" idle={persona.get('session_reset_idle_minutes', 30)}m"
    else:
        detail = ""
    print(f"  session_reset={mode}{detail}")
    print(f"  personality_v{persona.get('version', 0)}: {preview}")
    print(f"  heartbeat_instructions: {field_status(persona, 'heartbeat_instructions')}")
    print(f"  user_context: {field_status(persona, 'user_context')}")
    if persona.get("onboarding_phase"):
        print(f"  onboarding_phase: {persona['onboarding_phase']}")
