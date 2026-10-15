"""Reconcile first-party client registrations from environment configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.middleware.access_control_auth import invalidate_client_cache
from app.models import Client
from app.services.project_permission_service import is_registry_synced_client


@dataclass(frozen=True)
class FirstPartyClientSpec:
    """Expected registration for a first-party client."""

    client_id: str
    display_name: str
    client_type: str
    allowed_projects: tuple[str, ...] | None


def _clean_client_id(value: str) -> str:
    return value.strip()


def _parse_allowed_projects(value: str | None) -> list[str] | None:
    if value is None:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _iter_first_party_client_specs() -> list[FirstPartyClientSpec]:
    specs: list[FirstPartyClientSpec] = []
    seen_client_ids: set[str] = set()

    def add(
        client_id: str,
        display_name: str,
        client_type: str,
        allowed_projects: tuple[str, ...] | None,
    ) -> None:
        cleaned = _clean_client_id(client_id)
        if not cleaned or cleaned in seen_client_ids:
            return
        seen_client_ids.add(cleaned)
        specs.append(
            FirstPartyClientSpec(
                client_id=cleaned,
                display_name=display_name,
                client_type=client_type,
                allowed_projects=allowed_projects,
            )
        )

    add(
        settings.agent_hub_dashboard_client_id,
        "agent-hub-dashboard",
        "internal",
        ("agent-hub",),
    )
    add(
        "portfolio-ai",
        "portfolio-ai",
        "internal",
        ("portfolio-ai",),
    )
    add(
        "monkey-fight",
        "monkey-fight",
        "external",
        ("monkey-fight",),
    )
    add(
        settings.summitflow_client_id,
        "summitflow",
        "internal",
        ("summitflow", "agent-hub"),
    )
    add(
        settings.portfolio_client_id,
        "portfolio-ai",
        "internal",
        ("portfolio-ai",),
    )
    add(
        settings.monkey_fight_client_id,
        "monkey-fight",
        "external",
        ("monkey-fight",),
    )
    return specs


async def reconcile_first_party_clients(db: AsyncSession) -> list[str]:
    """Ensure configured first-party client IDs exist with the expected shape."""
    changed_client_ids: list[str] = []

    for spec in _iter_first_party_client_specs():
        result = await db.execute(select(Client).where(Client.id == spec.client_id))
        client = result.scalar_one_or_none()
        desired_projects = (
            list(spec.allowed_projects) if spec.allowed_projects is not None else None
        )
        current_projects = (
            _parse_allowed_projects(client.allowed_projects) if client is not None else None
        )
        if client is not None and is_registry_synced_client(spec.display_name):
            # Registry sync owns this list (registered projects); seed it only on insert.
            desired_projects = current_projects
        desired_allowed_projects = (
            json.dumps(desired_projects) if desired_projects is not None else None
        )

        if client is None:
            db.add(
                Client(
                    id=spec.client_id,
                    display_name=spec.display_name,
                    client_type=spec.client_type,
                    status="active",
                    allowed_projects=desired_allowed_projects,
                )
            )
            changed_client_ids.append(spec.client_id)
            continue

        updated = False
        if client.display_name != spec.display_name:
            client.display_name = spec.display_name
            updated = True
        if client.client_type != spec.client_type:
            client.client_type = spec.client_type
            updated = True
        if current_projects != desired_projects:
            client.allowed_projects = desired_allowed_projects
            updated = True

        if updated:
            changed_client_ids.append(spec.client_id)

    if changed_client_ids:
        await db.commit()
        for client_id in changed_client_ids:
            invalidate_client_cache(client_id)

    return changed_client_ids


async def seed_automation_owner_clients(db: AsyncSession) -> list[str]:
    """Insert missing owner identities without changing existing registrations."""
    specs = (
        (settings.portfolio_client_id, "portfolio-ai"),
        (settings.jobinator_client_id, "jobinator-4000"),
        (settings.neri_client_id, "neri"),
    )
    inserted: list[str] = []
    for client_id, project_id in specs:
        if not client_id or await db.get(Client, client_id) is not None:
            continue
        db.add(Client(
            id=client_id,
            display_name=project_id,
            client_type="service",
            status="active",
            allowed_projects=json.dumps([project_id]),
        ))
        inserted.append(project_id)
    if inserted:
        await db.commit()
    return inserted
