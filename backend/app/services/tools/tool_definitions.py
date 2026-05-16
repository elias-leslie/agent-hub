"""Standard tool definitions for agent tool execution.

Defines the schema and metadata for all agent tools. Tool definitions are
split into focused sub-modules; this module re-exports everything for
backward compatibility and provides the agent tool registry.
"""

from __future__ import annotations

from app.services.tools._ideator_tools import (
    CREATE_TASK_TOOL,
    SUBMIT_IDEA_TOOL,
    get_ideator_public_tools,
    get_ideator_tools,
)
from app.services.tools._notification_tools import SEND_PUSH_TOOL
from app.services.tools._persona_tools import (
    CANCEL_CONSULTATION_TOOL,
    CANCEL_SCHEDULED_JOB_TOOL,
    INSPECT_SESSION_TOOL,
    LIST_CONSULTATIONS_TOOL,
    LIST_SCHEDULED_JOBS_TOOL,
    LOG_AGENT_PERFORMANCE_TOOL,
    MANAGE_MEMORY_TAGS_TOOL,
    MANAGE_MODEL_CONFIG_TOOL,
    MANAGE_TASKS_TOOL,
    MARK_MEMORY_IRRELEVANT_TOOL,
    MARK_MEMORY_RELEVANT_TOOL,
    READ_PERSONALITY_TOOL,
    READ_USER_CONTEXT_TOOL,
    REVIEW_AGENT_PERFORMANCE_TOOL,
    REVIEW_MEMORY_SYSTEM_TOOL,
    SCHEDULE_JOB_TOOL,
    SEARCH_PERSONA_HISTORY_TOOL,
    STEER_CONSULTATION_TOOL,
    SUBMIT_ONBOARDING_TOOL,
    WRITE_PERSONALITY_TOOL,
    WRITE_USER_CONTEXT_TOOL,
)
from app.services.tools._standard_tools import (
    BASH_TOOL,
    BATCH_EXECUTE_TOOL,
    CONSULT_AGENT_TOOL,
    EDIT_FILE_TOOL,
    FETCH_WEB_PAGE_TOOL,
    PRECISION_CODE_SEARCH_TOOL,
    PROPOSE_COMMITTEE_TOOL,
    PROPOSE_HONING_TOOL,
    PROPOSE_THOROUGH_TOOL,
    READ_FILE_TOOL,
    RESEARCH_WEB_TOOL,
    SEARCH_SCRATCH_CONTEXT_TOOL,
    SEARCH_WEB_TOOL,
    STANDARD_TOOLS,
    WRITE_FILE_TOOL,
    get_standard_tools,
)
from app.services.tools._tool_constants import DEFAULT_TIMEOUT
from app.services.tools.base import Tool

__all__ = [
    "BASH_TOOL",
    "BATCH_EXECUTE_TOOL",
    "CANCEL_CONSULTATION_TOOL",
    "CANCEL_SCHEDULED_JOB_TOOL",
    "CONSULT_AGENT_TOOL",
    "CREATE_TASK_TOOL",
    "DEFAULT_TIMEOUT",
    "EDIT_FILE_TOOL",
    "FETCH_WEB_PAGE_TOOL",
    "INSPECT_SESSION_TOOL",
    "LIST_CONSULTATIONS_TOOL",
    "LIST_SCHEDULED_JOBS_TOOL",
    "LOG_AGENT_PERFORMANCE_TOOL",
    "MANAGE_MEMORY_TAGS_TOOL",
    "MANAGE_MODEL_CONFIG_TOOL",
    "MANAGE_TASKS_TOOL",
    "MARK_MEMORY_IRRELEVANT_TOOL",
    "MARK_MEMORY_RELEVANT_TOOL",
    "PRECISION_CODE_SEARCH_TOOL",
    "PROPOSE_COMMITTEE_TOOL",
    "PROPOSE_HONING_TOOL",
    "PROPOSE_THOROUGH_TOOL",
    "READ_FILE_TOOL",
    "READ_PERSONALITY_TOOL",
    "READ_USER_CONTEXT_TOOL",
    "REVIEW_AGENT_PERFORMANCE_TOOL",
    "REVIEW_MEMORY_SYSTEM_TOOL",
    "SCHEDULE_JOB_TOOL",
    "SEARCH_PERSONA_HISTORY_TOOL",
    "SEARCH_SCRATCH_CONTEXT_TOOL",
    "SEARCH_WEB_TOOL",
    "SEND_PUSH_TOOL",
    "STANDARD_TOOLS",
    "STEER_CONSULTATION_TOOL",
    "SUBMIT_IDEA_TOOL",
    "SUBMIT_ONBOARDING_TOOL",
    "WRITE_FILE_TOOL",
    "WRITE_PERSONALITY_TOOL",
    "WRITE_USER_CONTEXT_TOOL",
    "get_agent_tool_specs",
    "get_agent_tools",
    "get_ideator_public_tools",
    "get_ideator_tools",
    "get_standard_tools",
]

# Agent slug → tool definitions mapping
_AGENT_TOOL_REGISTRY: dict[str, list[Tool]] = {
    "ideator": [CREATE_TASK_TOOL],
    "ideator-public": [SUBMIT_IDEA_TOOL],
    "persona": [
        *STANDARD_TOOLS,
    ],
    "governance-auditor": [
        *STANDARD_TOOLS,
    ],
    "memory-curator": [
        *STANDARD_TOOLS,
        REVIEW_MEMORY_SYSTEM_TOOL,
    ],
    # Vantage's research studio agent: read-only web research surface plus
    # three mode-recommendation tools. Excludes bash/edit/write — see
    # vantage/backend/app/services/research_orchestrator.py.
    "vantage-research": [
        RESEARCH_WEB_TOOL,
        SEARCH_WEB_TOOL,
        FETCH_WEB_PAGE_TOOL,
        PROPOSE_THOROUGH_TOOL,
        PROPOSE_COMMITTEE_TOOL,
        PROPOSE_HONING_TOOL,
    ],
}


def get_agent_tools(agent_slug: str) -> list[dict[str, object]] | None:
    """Get tool definitions for an agent by slug.

    Returns tools as dicts (ready for adapter consumption), or None if
    the agent has no registered tools.
    """
    tools = _AGENT_TOOL_REGISTRY.get(agent_slug)
    if not tools:
        return None
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]


def get_agent_tool_specs(agent_slug: str) -> list[Tool] | None:
    """Return raw Tool specs for internal provisioning paths."""
    tools = _AGENT_TOOL_REGISTRY.get(agent_slug)
    return tools.copy() if tools else None
