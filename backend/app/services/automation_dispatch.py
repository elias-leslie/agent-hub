"""Durable due dispatch and owner receipt reconciliation."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
import yaml
from hatchet_sdk.clients.admin import TriggerWorkflowOptions
from hatchet_sdk.exceptions import DedupeViolationError, FailedTaskRunExceptionGroup
from sqlalchemy import select

from app.config import settings
from app.core.project_roots import resolve_project_root
from app.db import async_session
from app.models import (
    AutomationDefinition,
    AutomationProfile,
    AutomationProjectPolicy,
    AutomationRun,
)
from app.services.automations import (
    admit_run,
    current_definitions,
    next_due,
    owner_policy_keys,
    owner_sync_pending,
    policy_sync_pending,
)

logger = logging.getLogger(__name__)


def _owner_api_base(project_id: str) -> str:
    """Resolve only a registered project's local API origin."""
    root = resolve_project_root(project_id)
    if root is None:
        raise RuntimeError(f"Owner project {project_id} has no registered root")
    index = yaml.safe_load((root / ".index.yaml").read_text())
    url = index.get("urls", {}).get("api") if isinstance(index, dict) else None
    if not isinstance(url, str):
        raise RuntimeError(f"Owner project {project_id} has no registered API")
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Automation callback must use a registered loopback API")
    return url.rstrip("/")


async def _pending_owner_syncs() -> list[tuple[str, dict]]:
    """Owner projects whose registered policy keys changed since the last ack."""
    async with async_session() as db:
        owner_keys: dict[str, list[str]] = {}
        for definition in await current_definitions(db):
            keys = owner_policy_keys([definition])
            if keys:
                owner_keys.setdefault(definition.owner_project_id, [])
                owner_keys[definition.owner_project_id] = sorted({*owner_keys[definition.owner_project_id], *keys})
        pending = []
        for project_id, keys in owner_keys.items():
            policy = await db.get(AutomationProjectPolicy, project_id)
            if policy is None or not policy_sync_pending(policy, keys):
                continue
            pending.append((project_id, {
                "revision": policy.revision,
                "enabled": policy.enabled,
                "config": {key: policy.config[key] for key in keys},
            }))
        return pending


async def _sync_owner_policy(project_id: str, payload: dict) -> bool:
    revision = payload["revision"]
    try:
        if not settings.internal_service_secret:
            raise RuntimeError("Internal service secret is not configured")
        url = await asyncio.to_thread(_owner_api_base, project_id) + "/automations/policy/sync"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url, json=payload,
                headers={"X-Agent-Hub-Internal": settings.internal_service_secret},
            )
            response.raise_for_status()
    except (OSError, RuntimeError, httpx.HTTPError):
        logger.warning("%s automation policy revision %s awaits owner sync", project_id, revision, exc_info=True)
        return False
    async with async_session() as db:
        row = (await db.execute(select(AutomationProjectPolicy).where(
            AutomationProjectPolicy.project_id == project_id
        ).with_for_update())).scalar_one_or_none()
        if row is not None and row.sync_revision < revision:
            row.sync_revision = revision
            await db.commit()
    return True


async def sync_owner_policies(project_id: str | None = None) -> bool:
    """Mirror each changed policy revision to owners that registered policy keys.

    Runs of that project stay held (owner_policy_sync_pending) until the owner
    acknowledges the exact revision.
    """
    synced = True
    for owner, payload in await _pending_owner_syncs():
        if project_id is None or owner == project_id:
            synced = await _sync_owner_policy(owner, payload) and synced
    return synced


def _hatchet_task(target: str):
    from app.workflows.model_sync import model_enrichment_sync_task
    from app.workflows.scheduled import (
        data_retention_task,
        memory_cleanup_task,
        memory_governance_task,
        session_cleanup_task,
        tier_optimizer_task,
    )
    from app.workflows.session_reaper import session_reaper_task

    tasks = {
        "session_cleanup": session_cleanup_task,
        "session_reaper": session_reaper_task,
        "tier_optimizer": tier_optimizer_task,
        "memory_cleanup": memory_cleanup_task,
        "memory_governance": memory_governance_task,
        "data_retention": data_retention_task,
        "model_enrichment_sync": model_enrichment_sync_task,
    }
    if target not in tasks:
        raise RuntimeError(f"No direct Hatchet task for {target}")
    return tasks[target]


async def dispatch_run(run_id: str) -> None:
    """Send one admitted run; retries retain its stable owner occurrence ID."""
    async with async_session() as db:
        run = (await db.execute(select(AutomationRun).where(AutomationRun.id == run_id).with_for_update())).scalar_one_or_none()
        if run is None or run.status not in {"admitted", "dispatching", "accepted"}:
            return
        definition = await db.get(AutomationDefinition, (run.workflow_key, run.definition_version))
        profile = await db.get(AutomationProfile, run.profile_id)
        if definition is None or profile is None:
            raise RuntimeError("Automation definition or profile missing")
        dispatch_kind = definition.dispatch_kind
        dispatch_target = definition.dispatch_target
        owner_project_id = definition.owner_project_id
        if run.status == "accepted" and dispatch_kind != "callback":
            return
        if run.status != "accepted":
            run.status = "dispatching"
        payload = {
            "run_id": run.id, "profile_id": run.profile_id,
            "workflow_key": run.workflow_key.split("/", 1)[-1],
            "definition_version": run.definition_version,
            "profile_revision": run.profile_revision,
            "occurrence_key": run.occurrence_key, "trigger": run.trigger,
            "scheduled_for": (run.scheduled_for or run.created_at).isoformat(),
            "config": run.config_snapshot or {},
            "policy_config": run.policy_snapshot or {},
        }
        if owner_project_id == "summitflow":
            payload["project_id"] = profile.project_id
        await db.commit()

    try:
        if dispatch_kind == "hatchet":
            from app.workflows.scheduled import EmptyInput

            task = _hatchet_task(dispatch_target)
            try:
                ref = await task.aio_run_no_wait(
                    input=EmptyInput(automation_run_id=run_id),
                    options=TriggerWorkflowOptions(
                        key=run_id,
                        additional_metadata={"automation_run_id": run_id},
                    ),
                )
                owner_run_id = ref.workflow_run_id
            except DedupeViolationError:
                # The Hatchet trigger succeeded before our DB receipt commit.
                # Recover the same run instead of creating a second execution.
                from app.hatchet_app import get_hatchet

                matches = await get_hatchet().runs.aio_list_with_pagination(
                    additional_metadata={"automation_run_id": run_id}, limit=1,
                )
                owner_run_id = (
                    matches[0].workflow_run_external_id or matches[0].task_external_id
                    if matches else None
                )
                if not owner_run_id:
                    raise RuntimeError("Hatchet deduplicated run but its receipt is not visible yet") from None
            receipt = {"hatchet_run_id": owner_run_id}
        elif dispatch_kind == "callback":
            if not settings.internal_service_secret:
                raise RuntimeError("Internal service secret is not configured")
            url = await asyncio.to_thread(_owner_api_base, owner_project_id) + dispatch_target
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url, json=payload,
                    headers={
                        "X-Agent-Hub-Internal": settings.internal_service_secret,
                        "Idempotency-Key": run_id,
                    },
                )
                response.raise_for_status()
                receipt = response.json()
            if not isinstance(receipt, dict) or not receipt.get("owner_run_id"):
                raise RuntimeError("Owner callback returned no durable owner_run_id")
            owner_run_id = str(receipt["owner_run_id"])
        else:
            raise RuntimeError(f"Unsupported dispatch kind {dispatch_kind}")
    except Exception as exc:
        logger.exception("Automation dispatch failed for %s", run_id)
        async with async_session() as db:
            row = await db.get(AutomationRun, run_id)
            if row and row.status == "dispatching":
                row.status = "admitted"
                row.error = str(exc)
                await db.commit()
            elif row and row.status == "accepted":
                row.error = str(exc)
                await db.commit()
        return

    async with async_session() as db:
        row = await db.get(AutomationRun, run_id)
        if row and row.status in {"admitted", "dispatching", "accepted"}:
            if row.owner_run_id and row.owner_run_id != owner_run_id:
                row.status = "failed"
                row.error = "Owner returned a different receipt for the same run"
                row.completed_at = datetime.now(UTC)
                await db.commit()
                return
            row.owner_run_id = owner_run_id
            row.owner_receipt = receipt
            row.accepted_at = row.accepted_at or datetime.now(UTC)
            terminal = receipt.get("status") if dispatch_kind == "callback" else None
            row.status = terminal if terminal in {"succeeded", "failed", "skipped", "cancelled"} else "accepted"
            owner_error = receipt.get("error") if row.status != "accepted" else None
            if row.status != "accepted":
                row.completed_at = datetime.now(UTC)
            # A terminal receipt's error is the owner's reason for the outcome;
            # an accepted receipt only clears an earlier transient dispatch error.
            row.error = str(owner_error) if owner_error else None
            await db.commit()


async def dispatch_due() -> int:
    """Admit only profiles whose old clock has been explicitly fenced."""
    now = datetime.now(UTC)
    async with async_session() as db:
        ids = (await db.execute(select(AutomationProfile.id).where(
            AutomationProfile.clock_owner == "central",
            AutomationProfile.enabled.is_(True),
            AutomationProfile.next_run_at <= now,
        ))).scalars().all()
    admitted = 0
    for profile_id in ids:
        async with async_session() as db:
            profile = await db.get(AutomationProfile, profile_id)
            if profile is None or profile.next_run_at is None or profile.next_run_at > now:
                continue
            policy = await db.get(AutomationProjectPolicy, profile.project_id)
            if policy is not None and not policy.enabled:
                # A disabled project would only yield a rejected run per tick;
                # move the clock past now instead of recording that noise.
                profile.next_run_at = next_due(
                    profile.schedule_type, profile.schedule_value, profile.schedule_timezone, now
                )
                await db.commit()
                continue
            if policy is not None and await owner_sync_pending(db, policy):
                continue
            run = await admit_run(
                db, profile_id, trigger="scheduled", scheduled_for=profile.next_run_at,
                requested_by="automation-clock",
            )
            await db.commit()
            if run.status != "admitted":
                continue
            admitted += 1
            run_id = run.id
        await dispatch_run(run_id)
    return admitted


async def reconcile_runs() -> int:
    """Retry unaccepted dispatches and settle Agent Hub Hatchet receipts."""
    from app.hatchet_app import get_hatchet

    async with async_session() as db:
        rows = (await db.execute(select(AutomationRun).where(
            AutomationRun.status.in_(["admitted", "dispatching", "accepted"]),
        ))).scalars().all()
        pending = [(row.id, row.status, row.owner_run_id, row.workflow_key, row.definition_version) for row in rows]
    settled = 0
    for run_id, status, owner_run_id, workflow_key, version in pending:
        if status in {"admitted", "dispatching"}:
            await dispatch_run(run_id)
            continue
        if not owner_run_id:
            continue
        async with async_session() as db:
            definition = await db.get(AutomationDefinition, (workflow_key, version))
            dispatch_kind = definition.dispatch_kind if definition is not None else None
        if dispatch_kind != "hatchet":
            if dispatch_kind == "callback":
                await dispatch_run(run_id)
            continue
        try:
            # The Hatchet REST status route is unavailable on this deployment;
            # its workflow listener returns completed results through gRPC.
            output = await asyncio.wait_for(
                get_hatchet().runs.workflow_run_listener.aio_result(owner_run_id),
                timeout=2.0,
            )
            # A cancelled Hatchet run completes with no task output.
            terminal = "succeeded" if output else "cancelled"
        except TimeoutError:
            continue
        except FailedTaskRunExceptionGroup:
            terminal = "failed"
        except Exception:
            logger.warning("Could not reconcile Hatchet run %s", owner_run_id, exc_info=True)
            continue
        async with async_session() as db:
            row = await db.get(AutomationRun, run_id)
            if row and row.status == "accepted":
                row.status = terminal
                row.completed_at = datetime.now(UTC)
                await db.commit()
                settled += 1
    return settled
