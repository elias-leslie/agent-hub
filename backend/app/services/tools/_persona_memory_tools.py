"""Persona tool definitions: personality, journal, user context, and memory curation."""

from __future__ import annotations

from app.services.tools.base import Tool

# --- Personality self-modification tools ---

READ_PERSONALITY_TOOL = Tool(
    name="read_personality",
    description=(
        "Read your current personality document. This defines your personality, "
        "principles, and operating style. Use this to review before making changes."
    ),
    input_schema={"type": "object", "properties": {}},
)

WRITE_PERSONALITY_TOOL = Tool(
    name="write_personality",
    description=(
        "Update your personality document. Your personality evolves as you learn "
        "what works best. Only update when you've learned something fundamental "
        "about how you operate. Always tell the human when you update it."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "personality": {
                "type": "string",
                "description": "The new personality document (markdown)",
            },
            "reason": {
                "type": "string",
                "description": "Why you're updating your personality — what you learned",
            },
        },
        "required": ["personality", "reason"],
    },
)

# --- Journal tools ---

WRITE_JOURNAL_TOOL = Tool(
    name="write_journal",
    description=(
        "Write a journal entry for today. Use this to record observations, decisions, "
        "learnings, and user insights. Journal entries provide temporal continuity — "
        "recent entries are automatically included in your context."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The journal entry content (markdown)",
            },
            "entry_type": {
                "type": "string",
                "enum": ["observation", "decision", "learning", "user_insight"],
                "description": "Type of journal entry (default: observation)",
                "default": "observation",
            },
        },
        "required": ["content"],
    },
)

READ_JOURNAL_TOOL = Tool(
    name="read_journal",
    description=(
        "Read your recent journal entries. Returns entries from the last N days "
        "to review your observations, decisions, and learnings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "days_back": {
                "type": "integer",
                "description": "How many days of journal entries to retrieve (default: 7)",
                "default": 7,
            },
        },
    },
)

SEARCH_JOURNAL_TOOL = Tool(
    name="search_journal",
    description=(
        "Search your journal entries by content. Use when looking for specific "
        "past observations, decisions, or learnings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search text to find in journal entries",
            },
            "days_back": {
                "type": "integer",
                "description": "How many days back to search (default: 30)",
                "default": 30,
            },
        },
        "required": ["query"],
    },
)

# --- User context tools ---

WRITE_USER_CONTEXT_TOOL = Tool(
    name="write_user_context",
    description=(
        "Update your knowledge about the user. Record preferences, patterns, "
        "communication style, and other user-specific information you learn. "
        "This is cumulative — update with the full document each time."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "user_context": {
                "type": "string",
                "description": "The updated user context document (markdown)",
            },
        },
        "required": ["user_context"],
    },
)

READ_USER_CONTEXT_TOOL = Tool(
    name="read_user_context",
    description="Read your current knowledge about the user.",
    input_schema={"type": "object", "properties": {}},
)

# --- Memory curation tools ---

MARK_MEMORY_RELEVANT_TOOL = Tool(
    name="mark_memory_relevant",
    description=(
        "Mark a memory episode as relevant to you. Adds the 'persona-relevant' tag "
        "so the memory is included in your long-term context. Use when you encounter "
        "a memory that contains important operational patterns, user preferences, or "
        "system knowledge you should retain."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "memory_uuid": {
                "type": "string",
                "description": "UUID of the memory episode to mark as relevant",
            },
        },
        "required": ["memory_uuid"],
    },
)

MARK_MEMORY_IRRELEVANT_TOOL = Tool(
    name="mark_memory_irrelevant",
    description=(
        "Remove the 'persona-relevant' tag from a memory episode. Use when a "
        "previously marked memory is no longer relevant to your operation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "memory_uuid": {
                "type": "string",
                "description": "UUID of the memory episode to unmark",
            },
        },
        "required": ["memory_uuid"],
    },
)

# --- Onboarding tool ---

SUBMIT_ONBOARDING_TOOL = Tool(
    name="submit_onboarding",
    description=(
        "Submit the completed onboarding profile for approval. Call this after "
        "all 10 onboarding topics have been covered and the user confirms they're "
        "satisfied. The profile will be reviewed by two independent models — both "
        "must approve before onboarding is considered complete. If rejected, you'll "
        "receive feedback on what to follow up on."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": (
                    "A comprehensive summary of everything learned during onboarding, "
                    "organized by the 10 topic areas"
                ),
            },
        },
        "required": ["summary"],
    },
)
