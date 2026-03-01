"""Project and agent type constants."""

from __future__ import annotations

# Valid agent types supported by the platform
VALID_AGENT_TYPES = {"claude", "gemini", "openrouter", "openai", "xai", "zhipu", "minimax", "nvidia"}

# =============================================================================
# Valid Project IDs — mirrors SummitFlow projects table + utility scopes
# =============================================================================
# Update when new projects are registered in SummitFlow.
# Any project_id not in this set is rejected at session creation time.
VALID_PROJECT_IDS: frozenset[str] = frozenset({
    # Real projects (from SummitFlow projects table, each has root_path)
    "summitflow",
    "agent-hub",
    "portfolio-ai",
    "terminal",
    "monkey-fight",
    "persona-sandbox",
    # Utility scopes (CLI, internal services — no root_path)
    "st-cli",
    "claude-consultation",
    "consult",
    "agent-playground",
})
