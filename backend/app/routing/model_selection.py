"""Advisory task-type selection, using catalog capabilities and live preflight.

Policy is provider guidance and operator judgment, not benchmark evidence. No
request content or inferred task classification passes through this module.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.constants.catalog import get_model_entry, resolve_model
from app.services.agent_routing_completion import route_preflight_error

_POLICY_PATH = Path(__file__).parent / "model_selection_policy.json"
_POLICY = json.loads(_POLICY_PATH.read_text())


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_type: Literal["general", "coding", "reasoning", "visual_reasoning", "writing"]
    mode: Literal["advisory", "shadow", "automatic"] = "advisory"
    assigned_model: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:/-]+$")
    override_model: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:/-]+$")
    override_effort: Literal["low", "medium", "high", "xhigh"] | None = None
    requires_tools: bool = False
    requires_vision: bool = False

    @model_validator(mode="after")
    def validate_request(self) -> SelectionRequest:
        if self.mode == "shadow" and not self.assigned_model:
            raise ValueError("shadow mode requires assigned_model for comparison")
        if bool(self.override_effort) != bool(self.override_model):
            raise ValueError("override_model and override_effort must be supplied together")
        return self


async def select_model(request: SelectionRequest) -> dict:
    policy_data = _POLICY
    policy = policy_data["policies"][request.task_type]
    selected = resolve_model(request.override_model or policy["model"])
    effort = request.override_effort or policy["effort"]
    entry = get_model_entry(selected)
    reasons: list[str] = []
    if entry is None:
        reasons.append("Model is not active in the catalog")
    else:
        if not entry.capabilities.supports_chat:
            reasons.append("Model does not support chat workloads")
        if (request.requires_tools or policy.get("requires_tools")) and not entry.capabilities.supports_tool_execution:
            reasons.append("Model route does not support tool execution")
        if (request.requires_vision or policy.get("requires_vision")) and not entry.capabilities.has_vision:
            reasons.append("Model route does not support image input")
        if not entry.capabilities.has_thinking:
            reasons.append("Model route does not advertise reasoning effort")
        if effort == "xhigh" and not entry.capabilities.supports_xhigh:
            reasons.append("Model route does not advertise xhigh effort")
        if (entry.capabilities.thinking_level_map or {}).get(effort, effort) is None:
            reasons.append("Model route does not support the requested effort")
        error = await route_preflight_error(selected)
        if error is not None:
            reasons.append(str(error))
    # A future pilot needs a dated, task-specific qualification for this exact
    # route and effort. Provider guidance and seed scores alone never qualify.
    qualification = policy.get("qualification") or {}
    today = datetime.now(UTC).date().isoformat()
    qualified = bool(
        not request.override_model
        and qualification.get("kind") == "task_benchmark"
        and qualification.get("source")
        and qualification.get("assessed_at", "9999") <= today
        and qualification.get("valid_until", "") >= today
        and qualification.get("model") == selected
        and qualification.get("effort") == effort
    )
    return {
        "task_type": request.task_type,
        "mode": request.mode,
        "model": selected,
        "effort": effort,
        "override": request.override_model is not None,
        "available": not reasons,
        "unavailable_reasons": reasons,
        "checked_at": datetime.now(UTC).isoformat(),
        "availability_scope": "catalog, credentials and shared provider cooldown; not an entitlement or capability probe",
        "cost_comparison": "not evaluated; subscription quota and metered prices are not directly comparable",
        "provenance": {
            "kind": "explicit_override" if request.override_model else "provider_guidance_and_operator_judgment",
            "source": None if request.override_model else policy["source"],
            "source_checked_at": None if request.override_model else policy["source_checked_at"],
            "confidence": "unqualified",
            "rationale": "Caller selected the model and effort." if request.override_model else policy["rationale"],
            "policy_version": policy_data["version"],
            "benchmark_evidence": None,
        },
        "automatic_eligible": qualified,
        "apply": request.mode == "automatic" and qualified and not reasons,
        "automatic_reason": ("Task-specific qualification is current." if qualified else "No current task-specific benchmark qualification is configured."),
        "qualification": qualification or None,
        "shadow_comparison": (
            {"assigned_model": resolve_model(request.assigned_model), "same_model": resolve_model(request.assigned_model) == selected}
            if request.mode == "shadow" and request.assigned_model else None
        ),
    }
