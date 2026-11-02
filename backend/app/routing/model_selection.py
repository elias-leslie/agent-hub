"""Metadata-only advisory selection using catalog capabilities and live preflight."""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.constants.catalog import get_model_entry, resolve_model
from app.llm.model_resolver import resolve_llm_model
from app.llm.providers.google import _get_thinking_level
from app.llm.simple_options import clamp_reasoning
from app.routing.launch_policy import deny_reason, job_of, notes_for_models
from app.routing.launch_policy import load_policy as _load_policy
from app.services.agent_routing_completion import route_preflight_error
from app.services.session_roles import WORK_ROLES


class UnknownTaskType(ValueError):
    pass


class UnknownLaunchKey(ValueError):
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
        "model_notes": notes_for_models(policy_data, [item["model"] for item in attempts]),
        "shadow_comparison": (
            {"assigned_model": resolve_model(request.assigned_model), "same_model": resolve_model(request.assigned_model) == model}
            if request.mode == "shadow" and request.assigned_model else None
        ),
    }


def _launch_job(launch: dict, role: str) -> str:
    """A job id, or the job a registered work role launches as."""
    if (key := job_of(launch, role)) is not None:
        return key
    jobs = sorted(set(launch["jobs"]) - set(WORK_ROLES))
    raise UnknownLaunchKey(f"Unknown work role or job {role!r}. Work roles: {', '.join(WORK_ROLES)}. "
                           f"Other jobs: {', '.join(jobs)}.")


def _with_project_default(row: dict, project: str | None) -> dict:
    """The row with this project's own default laid over it, if the row names one. An alternate that
    is now the default drops out."""
    override = (row.get("projects") or {}).get(project) if project else None
    if not override:
        return row
    merged = {**row, **override, "project_default": project}
    merged["alternates"] = [alt for alt in row.get("alternates", [])
                            if (alt.get("model"), alt.get("effort")) != (merged["model"], merged["effort"])]
    return merged


def _launch_row(policy: dict, key: str, tool: str, *, work_role: str | None, model: str | None,
                project: str | None) -> dict:
    launch = policy["launch"]
    job = launch["jobs"][key]
    row = job["tools"].get(tool) or launch["tools"][tool].get("default") or {
        "model": None, "effort": None, "use": False, "why": f"No {tool} entry for this job."}
    row = _with_project_default(row, project)
    denied = deny_reason(policy, job=key, work_role=work_role, project=project, tool=tool,
                         model=model or row.get("model"))
    return {
        "job": key, "label": job["label"], "tool": tool, "model": row.get("model"), "effort": row.get("effort"),
        "daybreak": row.get("daybreak"), "context": job["context"], "use": denied is None and row.get("use", True),
        "launchable": row.get("launchable", True), "alternates": row.get("alternates", []),
        "subagent": job.get("subagent"), "work_roles": job.get("work_roles", []), "why": denied or row.get("why"),
        "note": launch["tools"][tool].get("note"), "allowed": denied is None, "deny_reason": denied,
        "project_default": row.get("project_default"), "when": row.get("when"),
    }


def launch_defaults(policy: dict, *, role: str | None = None, tool: str | None = None,
                    model: str | None = None, project: str | None = None) -> dict:
    """Rows of the launch table, optionally for one job/work role and one tool. Each row says whether the
    launch is allowed: the table's model, or ``model`` when the caller names one, is checked against the
    deny rows for this job, work role and project."""
    launch = policy["launch"]
    if tool is not None and tool not in launch["tools"]:
        raise UnknownLaunchKey(f"Unknown tool {tool!r}; use one of: {', '.join(launch['tools'])}")
    keys = [_launch_job(launch, role)] if role is not None else list(launch["jobs"])
    tools = [tool] if tool is not None else list(launch["tools"])
    work_role = role if role in WORK_ROLES else None
    rows = [_launch_row(policy, key, name, work_role=work_role, model=model, project=project)
            for key in keys for name in tools]
    shown = [m for row in rows if row["allowed"] for m in (row["model"], *(alt.get("model") for alt in row["alternates"]))]
    return {
        "version": policy["version"], "role": role, "work_role": work_role,
        "work_roles": list(WORK_ROLES), "about": launch["about"], "rows": rows,
        "model_notes": notes_for_models(policy, shown),
    }
