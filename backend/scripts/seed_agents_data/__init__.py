"""Agent definitions package.

This package contains agent definitions organized by category.
Re-exports all data for backward compatibility with the original module.
"""

from seed_agents_data.concierge_agents import CONCIERGE_AGENTS
from seed_agents_data.core_agents import CORE_AGENTS
from seed_agents_data.pipeline_agents import PIPELINE_AGENTS
from seed_agents_data.support_agents import SUPPORT_AGENTS

# Combine all agents in the original order
DEFAULT_AGENTS = CORE_AGENTS + PIPELINE_AGENTS + SUPPORT_AGENTS + CONCIERGE_AGENTS

# Agents to mark inactive (absorbed into other agents)
DEACTIVATE_SLUGS = ["worker", "auditor"]

# Fields that get updated on existing agents during upsert
UPSERT_FIELDS = [
    "name",
    "description",
    "system_prompt",
    "primary_model_id",
    "fallback_models",
    "escalation_model_id",
    "temperature",
    "is_coding_agent",
    "memory_config",
]

__all__ = [
    "CONCIERGE_AGENTS",
    "CORE_AGENTS",
    "DEACTIVATE_SLUGS",
    "DEFAULT_AGENTS",
    "PIPELINE_AGENTS",
    "SUPPORT_AGENTS",
    "UPSERT_FIELDS",
]
