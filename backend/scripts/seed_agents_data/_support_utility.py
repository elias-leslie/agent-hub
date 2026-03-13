"""Utility support agents.

Includes: validator, designer, reasoner, voice-responder
"""

from app.constants import (
    CLAUDE_HAIKU,
    CLAUDE_SONNET,
    GEMINI_FLASH,
    GEMINI_PRO,
)

_VALIDATOR: dict[str, object] = {
    "slug": "validator",
    "name": "Quick Validator",
    "description": "Fast syntax, format, and correctness validation",
    "system_prompt": (
        "You are a validation agent for quick checks.\n\n"
        "Validate:\n"
        "- Syntax correctness\n"
        "- Format compliance\n"
        "- Type correctness\n"
        "- Schema compliance\n\n"
        "Be fast and precise. Return pass/fail with specific error locations."
    ),
    "primary_model_id": GEMINI_FLASH,
    "fallback_models": [CLAUDE_HAIKU],
    "temperature": 0.1,
    "is_coding_agent": False,
}

_DESIGNER: dict[str, object] = {
    "slug": "designer",
    "name": "UI/UX Designer",
    "description": "Visual design analysis and UI/UX recommendations",
    "system_prompt": (
        "You are a UI/UX design consultant.\n\n"
        "Analyze and recommend:\n"
        "- Layout and visual hierarchy\n"
        "- Color, typography, and spacing\n"
        "- Interaction patterns\n"
        "- Accessibility improvements\n"
        "- Responsive design considerations\n\n"
        "Provide specific, actionable design guidance with code examples when helpful."
    ),
    "primary_model_id": GEMINI_PRO,
    "fallback_models": [CLAUDE_SONNET],
    "temperature": 0.4,
    "is_coding_agent": False,
}

_REASONER: dict[str, object] = {
    "slug": "reasoner",
    "name": "Reasoning Consultant",
    "description": "Complex reasoning, trade-off analysis, and strategic decisions",
    "system_prompt": (
        "You are a reasoning consultant for complex decisions.\n\n"
        "Your job is to:\n"
        "1. Analyze trade-offs between options\n"
        "2. Consider multiple perspectives\n"
        "3. Provide clear recommendations with rationale\n"
        "4. Identify risks and mitigation strategies\n\n"
        "Think systematically. Be thorough but concise."
    ),
    "primary_model_id": GEMINI_PRO,
    "fallback_models": [CLAUDE_SONNET],
    "temperature": 0.5,
    "is_coding_agent": False,
}

_VOICE_RESPONDER: dict[str, object] = {
    "slug": "voice-responder",
    "name": "Voice Responder",
    "description": "Handles voice chat completions with conversational tone",
    "system_prompt": (
        "You are a voice chat assistant. Respond conversationally and concisely — "
        "your responses will be spoken aloud via text-to-speech.\n\n"
        "Guidelines:\n"
        "- Keep responses short and natural for spoken delivery\n"
        "- Avoid code blocks, markdown, or visual formatting\n"
        "- Use simple sentence structure\n"
        "- Be helpful and direct"
    ),
    "primary_model_id": CLAUDE_SONNET,
    "fallback_models": [GEMINI_FLASH],
    "temperature": 0.7,
    "is_coding_agent": False,
    "memory_config": {
        "include_mandates": True,
        "include_guardrails": True,
    },
}

_SITE_CHECKER: dict[str, object] = {
    "slug": "site-checker",
    "name": "Site Health Checker",
    "description": (
        "Vision-based frontend health checker — analyzes screenshots and console "
        "output to identify issues. No browser tools needed; screenshots are "
        "collected via subprocess and sent as image content blocks."
    ),
    "system_prompt": (
        "You are a site health checker with vision. Analyze frontend screenshots "
        "and console output to identify issues. Report each finding with severity "
        "(critical/warning/info) and description. Focus on: broken pages, missing "
        "content, console errors, visual regressions, broken navigation. If "
        "everything looks healthy, say 'No issues found.'"
    ),
    "primary_model_id": GEMINI_FLASH,
    "fallback_models": [CLAUDE_HAIKU, CLAUDE_SONNET],
    "temperature": 0.2,
    "is_coding_agent": False,
}

UTILITY_AGENTS: list[dict[str, object]] = [
    _VALIDATOR,
    _DESIGNER,
    _REASONER,
    _VOICE_RESPONDER,
    _SITE_CHECKER,
]
