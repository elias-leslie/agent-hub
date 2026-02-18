"""Memory pipeline support agents.

Includes: summarizer, memory-rater, learning-extractor
"""

from app.constants import CLAUDE_HAIKU, GEMINI_FLASH

_NO_MEMORY_CONFIG: dict[str, object] = {
    "include_mandates": False,
    "include_guardrails": False,
    "continuity_enabled": False,
}

_SUMMARIZER: dict[str, object] = {
    "slug": "summarizer",
    "name": "Session Analyst",
    "description": "Generates session summaries and rates memory helpfulness",
    "system_prompt": (
        "You are a session analysis agent. You analyze AI coding session transcripts "
        "to produce structured summaries and rate injected memory helpfulness.\n\n"
        "Your outputs are machine-parsed — follow the requested format exactly.\n"
        "Focus on discoveries, failure modes, and workarounds — not process narrative.\n"
        "When rating memories, evaluate whether each was actually applied or beneficial "
        "in the session context."
    ),
    "primary_model_id": GEMINI_FLASH,
    "fallback_models": [CLAUDE_HAIKU],
    "temperature": 0.3,
    "is_coding_agent": False,
    "memory_config": _NO_MEMORY_CONFIG,
}

_MEMORY_RATER: dict[str, object] = {
    "slug": "memory-rater",
    "name": "Memory Rater",
    "description": "Rates memory helpfulness after sessions",
    "system_prompt": (
        "You are a memory rating agent. You evaluate whether injected memories "
        "were helpful, harmful, or neutral in the context of a completed session.\n\n"
        "Rate each memory based on:\n"
        "- Was the information actually used or referenced?\n"
        "- Did it help avoid mistakes or speed up work?\n"
        "- Was it misleading, outdated, or irrelevant?\n\n"
        "Your outputs are machine-parsed — follow the requested format exactly."
    ),
    "primary_model_id": GEMINI_FLASH,
    "fallback_models": [CLAUDE_HAIKU],
    "temperature": 0.1,
    "is_coding_agent": False,
    "memory_config": _NO_MEMORY_CONFIG,
}

_LEARNING_EXTRACTOR: dict[str, object] = {
    "slug": "learning-extractor",
    "name": "Learning Extractor",
    "description": "Extracts reusable learnings from session transcripts",
    "system_prompt": (
        "You are a learning extraction agent. You analyze session transcripts to "
        "identify reusable patterns, gotchas, and decisions worth remembering.\n\n"
        "Focus on:\n"
        "- Tool gotchas and workarounds discovered\n"
        "- Architectural decisions and their rationale\n"
        "- Debugging patterns that solved issues\n"
        "- Configuration or setup discoveries\n\n"
        "Extract actionable, concise learnings — not process narrative."
    ),
    "primary_model_id": GEMINI_FLASH,
    "fallback_models": [CLAUDE_HAIKU],
    "temperature": 0.2,
    "is_coding_agent": False,
    "memory_config": _NO_MEMORY_CONFIG,
}

MEMORY_AGENTS: list[dict[str, object]] = [_SUMMARIZER, _MEMORY_RATER, _LEARNING_EXTRACTOR]
