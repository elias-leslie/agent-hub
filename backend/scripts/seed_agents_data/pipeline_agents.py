"""Pipeline agents for task management and code quality.

Includes: ideator, ideator-public, triager, debugger, test-writer, optimizer, ux-polisher

Agent definitions are split into focused sub-modules:
- _ideator_agents: conversational task creation agents
- _execution_agents: code quality and delivery agents
"""

from ._execution_agents import EXECUTION_AGENTS
from ._ideator_agents import IDEATOR_AGENTS

PIPELINE_AGENTS = IDEATOR_AGENTS + EXECUTION_AGENTS
