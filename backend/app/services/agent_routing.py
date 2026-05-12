"""Agent Routing Service.

Provides unified agent routing logic for all endpoints, including:
- Agent resolution (slug -> AgentDTO)
- System prompt injection
- Fallback chain completion
- Provider adapter management

Mandates are injected via the progressive context system (semantic search)
rather than agent-specific tags.

This service consolidates routing logic previously in openai_compat.py
for use by the native /api/complete endpoint.
"""

from .agent_routing_completion import (
    complete_with_fallback,
    inject_system_prompt_into_messages,
)
from .agent_routing_models import CompletionResult, MandateInjection, ResolvedAgent
from .agent_routing_utils import (
    get_provider_for_model,
    inject_agent_mandates,
    resolve_agent,
)

# Explicitly re-export
__all__ = [
    "CompletionResult",
    "MandateInjection",
    "ResolvedAgent",
    "complete_with_fallback",
    "get_provider_for_model",
    "inject_agent_mandates",
    "inject_system_prompt_into_messages",
    "resolve_agent",
]
