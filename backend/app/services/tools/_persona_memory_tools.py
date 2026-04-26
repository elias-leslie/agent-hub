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
    category="persona-memory",
    search_keywords=["personality", "operating style"],
    usage_examples=["Read the current personality document before revising it."],
    defer_loading=True,
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
    category="persona-memory",
    search_keywords=["update personality", "rewrite principles"],
    usage_examples=["Update the personality document after learning a durable operating preference."],
    defer_loading=True,
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
    category="persona-memory",
    search_keywords=["user preferences", "user profile"],
    usage_examples=["Record a stable user preference after confirming it."],
    defer_loading=True,
)

READ_USER_CONTEXT_TOOL = Tool(
    name="read_user_context",
    description="Read your current knowledge about the user.",
    input_schema={"type": "object", "properties": {}},
    category="persona-memory",
    search_keywords=["user context", "preferences"],
    usage_examples=["Review stored user context before making a broad assumption."],
    defer_loading=True,
)

# --- Heartbeat instructions tools ---

READ_HEARTBEAT_INSTRUCTIONS_TOOL = Tool(
    name="read_heartbeat_instructions",
    description=(
        "Read your current heartbeat instructions. These define what you do during "
        "periodic background check-ins. Review before making changes."
    ),
    input_schema={"type": "object", "properties": {}},
    category="persona-memory",
    search_keywords=["heartbeat", "background workflow"],
    usage_examples=["Read heartbeat instructions before changing recurring behavior."],
    defer_loading=True,
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
    category="persona-memory",
    search_keywords=["update heartbeat", "background workflow"],
    usage_examples=["Refine heartbeat instructions after a recurring failure mode is confirmed."],
    defer_loading=True,
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
    category="memory",
    search_keywords=["promote memory", "retain memory"],
    usage_examples=["Mark a durable operational pattern as persona-relevant."],
    defer_loading=True,
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
    category="memory",
    search_keywords=["demote memory", "remove memory relevance"],
    usage_examples=["Remove persona relevance from outdated memory guidance."],
    defer_loading=True,
)

MANAGE_MEMORY_TAGS_TOOL = Tool(
    name="manage_memory_tags",
    description=(
        "Inspect or edit tags on a memory episode so reference-tier routing can be corrected "
        "without rewriting mandates or prompts. Use this for role/domain audience tags on "
        "reference memories, not for filtering mandates or guardrails."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get_tags", "add_tags", "remove_tags"],
                "description": "Whether to inspect or update the memory's tags",
            },
            "memory_uuid": {
                "type": "string",
                "description": "UUID or UUID prefix of the memory episode",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags to add or remove (required for add_tags/remove_tags)",
            },
        },
        "required": ["action", "memory_uuid"],
    },
    category="memory",
    search_keywords=["memory tags", "audience tags", "reference routing"],
    usage_examples=["Add debugger-relevant to a reference memory after a repeated retrieval miss."],
    defer_loading=True,
)

REVIEW_MEMORY_SYSTEM_TOOL = Tool(
    name="review_memory_system",
    description=(
        "Inspect, run, or schedule memory-system review in one call. Uses the dedicated "
        "memory-curator agent as reviewer, compact batches, oldest-first review cadence, "
        "and persists review metadata. Use this instead of shelling out to several memory commands."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "run_due", "schedule"],
                "description": "status=inspect review queue, run_due=run one or more batches, schedule=create recurring review job",
                "default": "status",
            },
            "batch_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 25,
                "description": "Memories per reviewer prompt; capped for token efficiency",
                "default": 20,
            },
            "max_batches": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "description": "Maximum batches for run_due in this single tool call",
                "default": 1,
            },
            "cadence_days": {
                "type": "integer",
                "minimum": 1,
                "maximum": 365,
                "description": "Review memories not reviewed within this many days",
                "default": 45,
            },
            "reviewer_agent_slug": {
                "type": "string",
                "description": "Dedicated reviewer agent slug; must be memory-curator",
                "default": "memory-curator",
            },
            "dry_run": {
                "type": "boolean",
                "description": "Run reviewer without mutating memories",
                "default": False,
            },
            "include_archived": {
                "type": "boolean",
                "description": "Also review archived memories; use for full validation sweeps, not normal cadence",
                "default": False,
            },
            "schedule_type": {
                "type": "string",
                "enum": ["at", "every", "cron"],
                "description": "Required for schedule action",
            },
            "schedule_value": {
                "type": "string",
                "description": "ISO datetime, interval ms, or cron expression for schedule action",
            },
            "timezone": {
                "type": "string",
                "description": "IANA timezone for cron scheduling",
                "default": "UTC",
            },
        },
    },
    category="memory",
    search_keywords=["memory review", "memory quality", "curate memories", "last reviewed"],
    usage_examples=["Run all currently due memory reviews with max_batches set high enough for the queue."],
    defer_loading=True,
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
    category="persona-ops",
    search_keywords=["onboarding", "submit profile"],
    usage_examples=["Submit onboarding only after the user confirms the profile is complete."],
    defer_loading=True,
)
