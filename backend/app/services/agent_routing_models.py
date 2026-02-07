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


@dataclass
class MandateInjection:
    """Result of mandate injection."""

    system_content: str  # Agent system prompt + mandates
    injected_uuids: list[str]  # UUIDs of injected mandates


@dataclass
class CompletionResult:
    """Result of completion with fallback."""

    result: Any  # Adapter result
    model_used: str  # Model that produced the result
    used_fallback: bool  # Whether fallback was used
