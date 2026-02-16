"""Agent definitions for seeding the database.

This module re-exports all agent data from the seed_agents_data package.
Maintained for backward compatibility with existing imports.

The actual agent definitions are now organized by category:
- seed_agents_data.core_agents: Core pipeline agents (coder, planner, reviewer, refactor)
- seed_agents_data.pipeline_agents: Pipeline agents (ideator, triager, fixer, etc.)
- seed_agents_data.support_agents: Support agents (supervisor, analyst, qa, etc.)
"""

from seed_agents_data import (
    CORE_AGENTS,
    DEACTIVATE_SLUGS,
    DEFAULT_AGENTS,
    PIPELINE_AGENTS,
    SUPPORT_AGENTS,
)

__all__ = [
    "CORE_AGENTS",
    "DEACTIVATE_SLUGS",
    "DEFAULT_AGENTS",
    "PIPELINE_AGENTS",
    "SUPPORT_AGENTS",
]
