"""Reconcile first-party client registrations from environment configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
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


def _serialize_allowed_projects(projects: tuple[str, ...] | None) -> str | None:
    if projects is None:
        return None
    return json.dumps(list(projects))


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
        settings.agent_hub_telegram_client_id,
        "agent-hub-telegram-bot",
        "internal",
        ("agent-hub",),
    )
    add(
        "summitflow",
        "summitflow",
        "internal",
        ("summitflow", "agent-hub"),
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
    # Hermes: terminal/CLI agent companion. Empty allowed_projects (None)
    # means it can read/write across all projects — Hermes is a generic
    # tool, not a project-siloed service. scope_id at the call site
    # (profile:<name>) keeps the data properly partitioned.
    if settings.hermes_client_id:
        add(
            settings.hermes_client_id,
            "hermes",
            "external",
            tuple(settings.hermes_allowed_projects) if settings.hermes_allowed_projects else None,
        )

    return specs


async def reconcile_first_party_clients(db: AsyncSession) -> list[str]:
    """Ensure configured first-party client IDs exist with the expected shape."""
    changed_client_ids: list[str] = []

    for spec in _iter_first_party_client_specs():
        result = await db.execute(select(Client).where(Client.id == spec.client_id))
        client = result.scalar_one_or_none()
        desired_allowed_projects = _serialize_allowed_projects(spec.allowed_projects)

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
        if _parse_allowed_projects(client.allowed_projects) != (
            list(spec.allowed_projects) if spec.allowed_projects is not None else None
        ):
            client.allowed_projects = desired_allowed_projects
            updated = True

        if updated:
            changed_client_ids.append(spec.client_id)

    if changed_client_ids:
        await db.commit()
        for client_id in changed_client_ids:
            invalidate_client_cache(client_id)

    return changed_client_ids
