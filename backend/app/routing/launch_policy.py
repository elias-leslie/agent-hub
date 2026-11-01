"""Launch hard rules: providers a job, work role or project never launches on.

The rules are policy data (``launch.deny`` and ``launch.providers`` in model_selection_policy.json).
``counts_as`` is the one place that decides whether a tool/model pair is a given provider
(``is_claude`` for Claude); launch-defaults and Agent Hub's own completion chain both use it.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.constants.catalog import get_model_entry, resolve_model
from app.models import Session
from app.services.session_roles import WORK_ROLES, session_work_role

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

POLICY_PATH = Path(__file__).parent / "model_selection_policy.json"
_DENY_KEYS = {"jobs", "work_roles", "projects", "provider", "reason", "source"}


def load_policy() -> dict:
    path = Path(settings.agent_hub_model_selection_policy_path) if settings.agent_hub_model_selection_policy_path else POLICY_PATH
    return json.loads(path.read_text())


def job_of(launch: dict, role: str) -> str | None:
    """A job id, or the job a registered work role launches as."""
    if role in launch["jobs"]:
        return role
    return next((key for key, job in launch["jobs"].items() if role in job.get("work_roles", [])), None)


def counts_as(rule: dict, *, tool: str | None = None, model: str | None = None) -> bool:
    """Whether launching ``model`` through ``tool`` is this provider: one of its tools, a model the
    catalog lists under one of its providers, or an id naming one of its families. Unknown ids
    that name none of them are not this provider."""
    if tool is not None and tool in rule.get("tools", []):
        return True
    if not model:
        return False
    entry = get_model_entry(model) or get_model_entry(resolve_model(model))
    if entry is not None and entry.provider in rule.get("catalog_providers", []):
        return True
    names = {model.lower(), resolve_model(model).lower()}
    return any(token in name for token in rule.get("name_tokens", []) for name in names)


def is_claude(policy: dict, *, tool: str | None = None, model: str | None = None) -> bool:
    return counts_as(policy["launch"]["providers"]["claude"], tool=tool, model=model)


def deny_rows(policy: dict, *, job: str | None, work_role: str | None, project: str | None) -> list[dict]:
    """The deny rows that apply to this job, work role and project (every selector a row names must match)."""
    return [
        row for row in policy["launch"].get("deny", [])
        if ("jobs" not in row or job in row["jobs"])
        and ("work_roles" not in row or work_role in row["work_roles"])
        and ("projects" not in row or project in row["projects"])
    ]


def deny_reason(policy: dict, *, job: str | None, work_role: str | None, project: str | None,
                tool: str | None, model: str | None) -> str | None:
    """Why this launch is refused, or None when no deny row covers it."""
    providers = policy["launch"]["providers"]
    for row in deny_rows(policy, job=job, work_role=work_role, project=project):
        if counts_as(providers[row["provider"]], tool=tool, model=model):
            return str(row["reason"])
    return None


def launch_policy_problems(policy: dict) -> list[str]:
    """Rows the launch table must not hold: malformed deny rows, the retired ``use`` switch, and a
    tools row (or alternate) that a deny row refuses in every project."""
    launch = policy["launch"]
    providers = launch.get("providers") or {}
    problems: list[str] = []
    for index, row in enumerate(launch.get("deny", [])):
        where = f"launch.deny[{index}]"
        if extra := set(row) - _DENY_KEYS:
            problems.append(f"{where}: unknown keys {sorted(extra)}")
        if row.get("provider") not in providers:
            problems.append(f"{where}: provider {row.get('provider')!r} is not in launch.providers")
        if not str(row.get("reason") or "").strip() or not str(row.get("source") or "").strip():
            problems.append(f"{where}: reason and source are required")
        if "jobs" not in row and "work_roles" not in row:
            problems.append(f"{where}: name jobs or work_roles")
        if unknown := set(row.get("jobs", [])) - set(launch["jobs"]):
            problems.append(f"{where}: unknown jobs {sorted(unknown)}")
        if unknown := set(row.get("work_roles", [])) - set(WORK_ROLES):
            problems.append(f"{where}: unknown work roles {sorted(unknown)}")
    for key, job in launch["jobs"].items():
        roles = set(job.get("work_roles", []))
        everywhere = [
            row for row in launch.get("deny", [])
            if row.get("provider") in providers and "projects" not in row
            and ("jobs" not in row or key in row["jobs"])
            and ("work_roles" not in row or (roles and roles <= set(row["work_roles"])))
        ]
        for tool, entry in job.get("tools", {}).items():
            if "use" in entry:
                problems.append(f"launch.jobs.{key}.tools.{tool}: 'use' is retired; a tool a job must not use is a deny row")
            for model in [entry.get("model"), *(alt.get("model") for alt in entry.get("alternates", []))]:
                for row in everywhere:
                    if counts_as(providers[row["provider"]], tool=tool, model=model):
                        problems.append(f"launch.jobs.{key}.tools.{tool} ({model}) contradicts deny row: {row['reason']}")
    return problems


@dataclass(frozen=True)
class LaunchDenial:
    """The providers a session's work role and project may never run on."""
    rules: tuple[tuple[dict, str], ...]

    @property
    def providers(self) -> set[str]:
        return {name for rule, _ in self.rules for name in rule.get("catalog_providers", [])}

    def blocks(self, model: str | None) -> str | None:
        return next((reason for rule, reason in self.rules if counts_as(rule, model=model)), None)


def denial_for(policy: dict, *, work_role: str | None, project: str | None) -> LaunchDenial | None:
    launch = policy["launch"]
    job = job_of(launch, work_role) if work_role else None
    rows = deny_rows(policy, job=job, work_role=work_role, project=project)
    return LaunchDenial(tuple((launch["providers"][row["provider"]], str(row["reason"])) for row in rows)) if rows else None


async def session_launch_denial(db: AsyncSession | None, session_id: str | None) -> LaunchDenial | None:
    """The deny rows for an Agent Hub session's declared work role and project, if any."""
    if db is None or not session_id:
        return None
    session = await db.get(Session, session_id)
    if session is None or (role := session_work_role(session)) is None:
        return None
    policy: dict[str, Any] = await asyncio.to_thread(load_policy)
    return denial_for(policy, work_role=role["id"], project=session.project_id)
