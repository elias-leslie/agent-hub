"""Models for Agent Routing Service."""

from dataclasses import dataclass
from typing import Any

from app.services.agent_service import AgentDTO


@dataclass
class ResolvedAgent:
    """Result of agent resolution."""

    agent: AgentDTO
    model: str  # Primary model ID
    provider: str  # Provider name ("claude", "gemini")
    routing_mode: str = "legacy"
    workload_profile: str = "general"
    routing_decision_id: str | None = None
    auto_candidate_model_id: str | None = None
    routing_canary_percent: float = 0.0


@dataclass
class MandateInjection:
    """Result of mandate injection."""

    system_content: str  # Agent system prompt + mandates
    injected_uuids: list[str]  # UUIDs of injected mandates


@dataclass
class FallbackCompletionResult:
    """Result of completion with fallback."""

    result: Any  # CompletionInternalResult
    model_used: str  # Model that produced the result
    used_fallback: bool  # Whether fallback was used
    fallback_reason: str | None = None  # Why the primary model was abandoned
