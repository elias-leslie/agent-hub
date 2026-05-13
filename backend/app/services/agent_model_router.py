"""Agent model assignment routing.

Registered agents own their primary, fallback, and escalation model chain.
This module intentionally does not score models, create manual route rows, or
apply workload overrides.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.catalog import resolve_model
from app.routing.registry import get_provider_for_model
from app.services.agent_dto import AgentDTO

RoutingMode = Literal["agent_assignment"]


@dataclass(frozen=True)
class RoutingContext:
    """Request metadata kept for call-site compatibility."""

    request_id: str | None = None
    session_id: str | None = None
    project_id: str | None = None
    task_type: str | None = None
    phase: str | None = None
    work_context: dict[str, Any] | None = None
    has_tools: bool = False
    requires_json: bool = False
    has_vision_input: bool = False
    requires_audio: bool = False
    max_context_tokens: int | None = None


@dataclass(frozen=True)
class ModelRoute:
    """Resolved model chain for one agent assignment."""

    mode: RoutingMode
    primary_model_id: str
    fallback_models: list[str]
    escalation_model_id: str | None
    provider: str
    score_breakdown: dict[str, Any] = field(default_factory=dict)

    @property
    def chain(self) -> list[str]:
        return _unique(
            [
                self.primary_model_id,
                *self.fallback_models,
                *([self.escalation_model_id] if self.escalation_model_id else []),
            ]
        )


class RoutingSelectionError(RuntimeError):
    """Raised when an agent cannot be resolved to an assigned model."""


@dataclass(frozen=True)
class _RouteCandidate:
    primary_model_id: str
    fallback_models: list[str]
    escalation_model_id: str | None
    score_breakdown: dict[str, Any]


async def resolve_model_route(
    _db: AsyncSession,
    agent: AgentDTO,
    _context: RoutingContext | None = None,
) -> tuple[AgentDTO, ModelRoute]:
    """Resolve an agent slug to the model chain stored on the agent row."""
    if not agent.primary_model_id:
        raise RoutingSelectionError(
            f"Agent '{agent.slug}' has no primary_model_id assignment"
        )

    selected = _agent_assignment_chain(agent)
    provider = get_provider_for_model(selected.primary_model_id)
    route = ModelRoute(
        mode="agent_assignment",
        primary_model_id=selected.primary_model_id,
        fallback_models=selected.fallback_models,
        escalation_model_id=selected.escalation_model_id,
        provider=provider,
        score_breakdown=selected.score_breakdown,
    )
    routed_agent = replace(
        agent,
        primary_model_id=route.primary_model_id,
        fallback_models=list(route.fallback_models),
        escalation_model_id=route.escalation_model_id,
    )
    return routed_agent, route


def _agent_assignment_chain(agent: AgentDTO) -> _RouteCandidate:
    return _RouteCandidate(
        primary_model_id=resolve_model(agent.primary_model_id),
        fallback_models=[resolve_model(model) for model in agent.fallback_models or []],
        escalation_model_id=resolve_model(agent.escalation_model_id)
        if agent.escalation_model_id
        else None,
        score_breakdown={"agent_assignment_chain": True},
    )


def _unique(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


__all__ = [
    "ModelRoute",
    "RoutingContext",
    "RoutingMode",
    "RoutingSelectionError",
    "resolve_model_route",
]
