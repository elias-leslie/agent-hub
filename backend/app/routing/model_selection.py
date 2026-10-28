"""Metadata-only advisory selection using catalog capabilities and live preflight."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import settings
from app.constants.catalog import get_model_entry, resolve_model
from app.llm.model_resolver import resolve_llm_model
from app.llm.providers.google import _get_thinking_level
from app.llm.simple_options import clamp_reasoning
from app.services.agent_routing_completion import route_preflight_error

_POLICY_PATH = Path(__file__).parent / "model_selection_policy.json"


def _load_policy() -> dict:
    path = Path(settings.agent_hub_model_selection_policy_path) if settings.agent_hub_model_selection_policy_path else _POLICY_PATH
    return json.loads(path.read_text())


class UnknownTaskType(ValueError):
    pass


async def selection_policy() -> dict:
    """Read the owning policy on each call without blocking the event loop."""
    return await asyncio.to_thread(_load_policy)


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_type: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
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


def _current_evidence(evidence: dict, *, kind: str, model: str, effort: str, task_type: str) -> bool:
    try:
        start = date.fromisoformat(evidence.get("assessed_at", ""))
        end = date.fromisoformat(evidence.get("valid_until", ""))
        in_window = start <= datetime.now(UTC).date() <= end
    except (TypeError, ValueError):
        return False
    return bool(
        evidence.get("kind") == kind and evidence.get("source") and in_window
        and evidence.get("model") == model and evidence.get("effort") == effort
        and evidence.get("task_type") == task_type
    )


async def _unavailable(model: str, effort: str, *, tools: bool, vision: bool) -> list[str]:
    entry = get_model_entry(model)
    if entry is None:
        return ["Model is not active in the catalog"]
    reasons = []
    if not entry.capabilities.supports_chat:
        reasons.append("Model does not support chat workloads")
    if tools and not entry.capabilities.supports_tool_execution:
        reasons.append("Model route does not support tool execution")
    if vision and not entry.capabilities.has_vision:
        reasons.append("Model route does not support image input")
    if not entry.capabilities.has_thinking:
        reasons.append("Model route does not advertise reasoning effort")
    if effort not in {"low", "medium", "high", "xhigh"}:
        reasons.append("Effort is not supported by the selection contract")
    elif effort == "xhigh" and not entry.capabilities.supports_xhigh:
        reasons.append("Model route does not advertise xhigh effort")
    if (entry.capabilities.thinking_level_map or {}).get(effort, effort) is None:
        reasons.append("Model route does not support the requested effort")
    error = await route_preflight_error(model)
    if error is not None:
        reasons.append(str(error))
    return reasons


def _effort_details(model: str, effort: str) -> dict:
    """Describe the Agent Hub completion route, not a separate native harness."""
    entry = get_model_entry(model)
    effective = None
    basis = "Provider or harness mapping not established"
    if entry and effort in {"low", "medium", "high", "xhigh"}:
        if entry.provider == "codex":
            effective = (entry.capabilities.thinking_level_map or {}).get(effort, effort)
            basis = "Agent Hub Codex Responses adapter and catalog map"
        elif entry.provider in {"google", "gemini"}:
            level = clamp_reasoning(effort)
            if level is not None and level != "xhigh":
                effective = _get_thinking_level(level, resolve_llm_model(model, entry.provider)).lower()
                basis = "Agent Hub Google adapter and catalog map"
    return {
        "requested": effort, "effective": effective, "basis": basis,
        "completion_request": "ultrathink" if effort == "xhigh" else effort,
        "scope": "Agent Hub completion adapter; provider execution not independently observed",
        "max_ultra": "unsupported by this selection and completion contract",
    }


async def select_model(request: SelectionRequest) -> dict:
    policy_data = await selection_policy()
    policy = policy_data["policies"].get(request.task_type)
    if policy is None:
        raise UnknownTaskType(f"Task type {request.task_type!r} is not in the selection policy")
    candidates: list[dict[str, Any]] = ([{"model": request.override_model, "effort": request.override_effort}]
                  if request.override_model else policy["candidates"])
    attempts = []
    chosen = None
    for candidate in candidates:
        model = resolve_model(candidate["model"])
        effort = candidate["effort"]
        reasons = await _unavailable(model, effort, tools=request.requires_tools or policy.get("requires_tools", False),
                                     vision=request.requires_vision or policy.get("requires_vision", False))
        attempts.append({"model": model, "effort": effort, "available": not reasons, "reasons": reasons})
        if not reasons:
            chosen = (candidate, model, effort)
            break
    candidate, model, effort = chosen if chosen else (candidates[0], resolve_model(candidates[0]["model"]), candidates[0]["effort"])
    effort_details = _effort_details(model, effort)
    qualification = candidate.get("qualification") or {}
    benchmark = qualification.get("benchmark") or {}
    local = qualification.get("local_route") or {}
    qualified = bool(
        chosen and not request.override_model
        and _current_evidence(benchmark, kind="task_benchmark", model=model, effort=effort, task_type=request.task_type)
        and _current_evidence(local, kind="local_route_qualification", model=model, effort=effort, task_type=request.task_type)
        and effort_details["effective"] is not None
        and local.get("effective_effort") == effort_details["effective"]
    )
    return {
        "task_type": request.task_type, "mode": request.mode, "model": model, "effort": effort,
        "effort_details": effort_details,
        "override": request.override_model is not None, "available": chosen is not None,
        "unavailable_reasons": attempts[0]["reasons"] if not chosen else [], "candidates_checked": attempts,
        "checked_at": datetime.now(UTC).isoformat(),
        "availability_scope": "catalog, credentials and shared provider cooldown; not an entitlement or capability probe",
        "cost_comparison": "not evaluated; subscription quota and metered prices are not directly comparable",
        "provenance": {
            "kind": "explicit_override" if request.override_model else "provider_guidance_and_operator_judgment",
            "source": candidate.get("source"), "source_checked_at": candidate.get("source_checked_at"),
            "confidence": "unqualified", "rationale": "Caller selected the model and effort." if request.override_model else candidate["rationale"],
            "policy_version": policy_data["version"], "benchmark_evidence": benchmark or None,
        },
        "automatic_eligible": qualified, "apply": request.mode == "automatic" and qualified,
        "automatic_reason": "Task benchmark and local route qualification are current." if qualified else "Current task benchmark and local route qualification are both required.",
        "qualification": qualification or None,
        "shadow_comparison": (
            {"assigned_model": resolve_model(request.assigned_model), "same_model": resolve_model(request.assigned_model) == model}
            if request.mode == "shadow" and request.assigned_model else None
        ),
    }
