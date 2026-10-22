"""Public lifecycle/settings facts; never retain prompts or compacted history."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._event_builders import _ParseState


def _fields(payload: dict, mapping: dict[str, str]) -> dict[str, Any]:
    return {
        target: value for key, target in mapping.items()
        if isinstance((value := payload.get(key)), (str, bool, int))
        and (not isinstance(value, str) or len(value) <= 512)
    }


def append_native_metadata(obj: dict, state: _ParseState) -> None:
    kind, payload = obj.get("type"), obj.get("payload")
    facts: dict[str, Any] = {}
    event_type = "native_lifecycle"
    if kind in {"event_msg", "turn_context", "compacted"} and isinstance(payload, dict):
        own_thread = state.codex_model_state.get("session_id")
        if state.codex_model_state.get("history_owner_thread_id") or (
            own_thread and payload.get("thread_id") not in {None, own_thread}
        ):
            return
        start = state.history_start_ordinal
        ordinal = obj.get("ordinal")
        if start is not None and isinstance(ordinal, int) and ordinal < start:
            return
        evidence = state.codex_model_state.get("evidence") or {}
        turn = payload.get("turn_id") or evidence.get("turn_id")
        if isinstance(turn, str):
            facts["native_turn_id"] = turn
        if kind == "turn_context":
            event_type = "native_settings"
            facts.update(source="codex.turn_context", **_fields(payload, {
                "model": "requested_model", "effort": "reasoning_effort",
                "service_tier": "service_tier", "cyber_access_program": "cyber_access_program",
                "approval_policy": "approval_policy",
            }))
        elif kind == "compacted":
            facts.update(source="codex.compacted", status="compacted", **_fields(payload, {
                "compaction_response_id": "response_id", "window_number": "window_number",
            }))
        elif payload.get("type") in {"task_started", "task_complete", "turn_aborted"}:
            native_type = payload["type"]
            error = payload.get("error")
            facts.update(source=f"codex.event_msg.{native_type}", status={
                "task_started": "started", "task_complete": "failed" if error else "completed",
                "turn_aborted": "aborted",
            }[native_type])
            if isinstance(error, dict):
                facts.update(_fields(error, {"codex_error_info": "native_category"}))
            facts.update(_fields(payload, {"reason": "reason", "duration_ms": "duration_ms"}))
        elif payload.get("type") == "thread_settings_applied":
            event_type = "native_settings"
            settings = payload.get("thread_settings")
            facts["source"] = "codex.event_msg.thread_settings_applied"
            if isinstance(settings, dict):
                facts.update(_fields(settings, {
                    "model": "requested_model", "reasoning_effort": "reasoning_effort",
                    "service_tier": "service_tier", "cyber_access_program": "cyber_access_program",
                    "approval_policy": "approval_policy",
                }))
        else:
            return
    elif kind == "system" and obj.get("subtype") == "compact_boundary":
        facts.update(source="claude.system.compact_boundary", status="compacted")
        metadata = obj.get("compactMetadata")
        if isinstance(metadata, dict):
            facts.update(_fields(metadata, {"trigger": "trigger", "preTokens": "pre_tokens"}))
    else:
        return
    # Stable across a remount or an unchanged file's relocation. This is a
    # metadata identity only: existing message/tool identities stay intact.
    digest = hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()
    saw_content, sequence = state._saw_content, state.sequence
    state.append(event_type, tool_output=facts, source_event_id=f"native_metadata:{digest}")
    state._saw_content = saw_content
    state.sequence = sequence
