"""Rows for deliveries whose harness part is unknown: remote-host sessions and harnesses we cannot read.

A remote host's transcript is not always mirrored here, and a surface without a transcript reader (Antigravity,
opencode, any other) has none, so there is no measured first turn. What is known is the delivery: its size, role and host. These
rows show that, with the total and the harness part unknown (None, shown as an em dash, never 0). A delivery that a
measured session already carries (usage_sessions.delivery_id) is not repeated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContextDelivery, UsageSession

# Delivery surface -> harness, for harnesses whose first turn we measure from transcripts or session files.
MEASURED_SURFACES = {"claude_code": "claude", "codex": "codex", "pi": "pi"}
# Every other surface is a harness whose transcript the collector cannot read: total and harness part stay unknown,
# never guessed. Deliveries made for Agent Hub's own agents (source "agent") are measured from cost_logs instead.
AGENT_SOURCE = "agent"


@dataclass(frozen=True)
class DeliveryOnlyRow:
    delivery_id: str
    harness: str
    host: str | None
    role: str | None
    coordinator: bool
    project: str | None
    model: str | None
    at: datetime
    ours_tokens: int
    total: None = None  # unknown
    harness_tokens: None = None  # unknown
    reason: str = ""


def harness_of(surface: str) -> str:
    return MEASURED_SURFACES.get(surface, surface)


async def delivery_only_rows(db: AsyncSession, *, since: datetime, until: datetime | None = None) -> list[DeliveryOnlyRow]:
    """Remote-host deliveries and deliveries of unreadable harnesses that no measured session carries."""
    bound = select(UsageSession.delivery_id).where(UsageSession.delivery_id.is_not(None))
    stmt = select(ContextDelivery).where(
        ContextDelivery.generated_at >= since, ContextDelivery.delivery_id.not_in(bound), ContextDelivery.source != AGENT_SOURCE
    )
    if until is not None:
        stmt = stmt.where(ContextDelivery.generated_at <= until)
    out = []
    for d in (await db.execute(stmt.order_by(ContextDelivery.generated_at))).scalars():
        harness = harness_of(d.surface)
        unreadable = d.surface not in MEASURED_SURFACES
        if d.host:
            reason = "remote host: transcript not measured here"
        elif unreadable:
            reason = f"{harness}: no readable transcript"
        else:
            continue
        out.append(DeliveryOnlyRow(
            d.delivery_id, harness, d.host, d.work_role, bool(d.coordinator), d.project_id, d.model, d.generated_at,
            int(d.est_tokens), reason=reason,
        ))
    return out
