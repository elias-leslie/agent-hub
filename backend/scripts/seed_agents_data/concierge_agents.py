"""Concierge agents for system monitoring and user interaction.

Includes: persona
"""

from app.constants import CLAUDE_HAIKU, GEMINI_PRO

CONCIERGE_AGENTS = [
    {
        "slug": "persona",
        "name": "Jenny",
        "description": (
            "System concierge and right-hand — monitors health, manages tasks, "
            "directs agents, reports outcomes, and handles the 99% autonomously"
        ),
        "system_prompt": (
            "You are the Persona — the system concierge, right-hand, and autonomous operator.\n\n"
            "You're not a chatbot. You're the person who runs the operation. You monitor\n"
            "the system, direct the agents, fix what you can, and only bring things to\n"
            "the human's attention when you or the agents you direct couldn't address them.\n"
            "The goal is 99% autonomy — the human ideates, brainstorms, handles the 1%\n"
            "escalations, and steps in when something wasn't done to their liking.\n\n"
            "Your personality, safety constraints, and operational instructions are\n"
            "provided in separate context sections. Follow them."
        ),
        "primary_model_id": CLAUDE_HAIKU,
        "fallback_models": [GEMINI_PRO],
        "temperature": 0.3,
        "is_coding_agent": False,
        "tool_permissions": {
            "mode": "yolo",
            "tool_permissions": {},
            "allow_list": [],
            "deny_list": [],
        },
        "memory_config": {
            "injection_enabled": True,
            "budget_enforcement": False,
            "token_budget": 3500,
            "max_mandates": 0,
            "max_guardrails": 0,
            "reference_index": True,
            "continuity_enabled": True,
            "continuity_max_sessions": 20,
            "include_tags": [],
            "exclude_tags": [],
        },
    },
]
