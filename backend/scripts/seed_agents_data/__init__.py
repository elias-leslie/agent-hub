"""Agent definitions package.

This package contains agent definitions organized by category.
Re-exports all data for backward compatibility with the original module.
"""

from .concierge_agents import CONCIERGE_AGENTS
from .core_agents import CORE_AGENTS
from .pipeline_agents import PIPELINE_AGENTS
from .portfolio_agents import PORTFOLIO_AGENTS
from .support_agents import SUPPORT_AGENTS

# Combine all agents in the original order
DEFAULT_AGENTS = CORE_AGENTS + PIPELINE_AGENTS + SUPPORT_AGENTS + PORTFOLIO_AGENTS + CONCIERGE_AGENTS

# Agents to mark inactive (absorbed into other agents)
DEACTIVATE_SLUGS = ["worker", "auditor"]

__all__ = [
    "CONCIERGE_AGENTS",
    "CORE_AGENTS",
    "DEACTIVATE_SLUGS",
    "DEFAULT_AGENTS",
    "PIPELINE_AGENTS",
    "PORTFOLIO_AGENTS",
    "SUPPORT_AGENTS",
]
