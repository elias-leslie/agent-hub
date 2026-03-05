"""Persona tool definitions: personality, user context, and memory curation."""

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
        "Update your personality document. IMPORTANT: You MUST call read_personality first "
        "and include ALL existing sections in your update — this tool replaces the full document. "
        "Only update when you've learned something fundamental about how you operate. "
        "Always tell the human when you update it. Dramatic shrinkage (>50%) will be rejected."
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

# --- User context tools ---

WRITE_USER_CONTEXT_TOOL = Tool(
    name="write_user_context",
    description=(
        "Update your knowledge about the user. IMPORTANT: You MUST call read_user_context first "
        "and include ALL existing sections in your update — this tool replaces the full document. "
        "Never submit a shorter document unless the user explicitly asked you to remove information. "
        "Dramatic shrinkage (>50%) will be rejected as a safety measure."
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

# --- Heartbeat instructions tools ---

READ_HEARTBEAT_INSTRUCTIONS_TOOL = Tool(
    name="read_heartbeat_instructions",
    description=(
        "Read your current heartbeat instructions. These define what you do during "
        "periodic background check-ins. Review before making changes."
    ),
    input_schema={"type": "object", "properties": {}},
)

WRITE_HEARTBEAT_INSTRUCTIONS_TOOL = Tool(
    name="write_heartbeat_instructions",
    description=(
        "Update your heartbeat instructions. IMPORTANT: You MUST call read_heartbeat_instructions "
        "first and include ALL existing sections in your update — this tool replaces the full document. "
        "Update when you discover better workflows for your background tasks. "
        "Dramatic shrinkage (>50%) will be rejected as a safety measure."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "heartbeat_instructions": {
                "type": "string",
                "description": "The new heartbeat instructions document (markdown)",
            },
            "reason": {
                "type": "string",
                "description": "Why you're updating heartbeat instructions — what you learned",
            },
        },
        "required": ["heartbeat_instructions", "reason"],
    },
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
