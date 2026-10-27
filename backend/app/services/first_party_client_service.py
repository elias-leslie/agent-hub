"""Reconcile first-party client registrations from environment configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.middleware.access_control_auth import invalidate_client_cache
from app.models import Client


@dataclass(frozen=True)
class FirstPartyClientSpec:
    """Expected registration for a first-party client."""

    client_id: str
    display_name: str
    client_type: str
    allowed_projects: tuple[str, ...] | None


def _clean_client_id(value: str) -> str:
    return value.strip()


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
    """Insert configured first-party client IDs that are missing.

    Existing registrations are left alone: the dashboard (and, for SummitFlow,
    registry sync) owns their name, type and project list after the first insert.
    """
    inserted: list[str] = []
    for spec in _iter_first_party_client_specs():
        if await db.get(Client, spec.client_id) is not None:
            continue
        db.add(
            Client(
                id=spec.client_id,
                display_name=spec.display_name,
                client_type=spec.client_type,
                status="active",
                allowed_projects=(
                    json.dumps(list(spec.allowed_projects))
                    if spec.allowed_projects is not None
                    else None
                ),
            )
        )
        inserted.append(spec.client_id)

    if inserted:
        await db.commit()
        for client_id in inserted:
            invalidate_client_cache(client_id)

    return inserted


async def seed_automation_owner_clients(db: AsyncSession) -> list[str]:
    """Insert missing owner identities without changing existing registrations."""
    specs = (
        (settings.portfolio_client_id, "portfolio-ai"),
        (settings.jobinator_client_id, "jobinator-4000"),
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
