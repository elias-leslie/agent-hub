"""Support agents for specialized tasks.

Includes: supervisor, analyst, validator, explorer, designer, reasoner, qa, summarizer
"""

from app.constants import (
    CLAUDE_HAIKU,
    CLAUDE_OPUS,
    CLAUDE_SONNET,
    GEMINI_FLASH,
    GEMINI_PRO,
)

SUPPORT_AGENTS = [
    {
        "slug": "supervisor",
        "name": "Supervisor Agent",
        "description": "Complex fix analysis, extension decisions, and coordination",
        "system_prompt": (
            "You are a supervisor agent for complex error analysis and coordination.\n\n"
            "Your responsibilities:\n"
            "1. Analyze errors that execution agents couldn't fix\n"
            "2. Decide whether to grant retry extensions (APPROVED/DENIED)\n"
            "3. Provide specific guidance for extended attempts\n"
            "4. Decide whether to continue past circuit breaker triggers (CONTINUE/BLOCK)\n\n"
            "Decision criteria for extensions:\n"
            "- Is there evidence of progress? (steps passing, code changes)\n"
            "- Is the remaining work achievable with more attempts?\n"
            "- Would a different approach help?\n\n"
            "Think step by step. Consider side effects. Be decisive."
        ),
        "primary_model_id": GEMINI_FLASH,
        "fallback_models": [CLAUDE_SONNET],
        "escalation_model_id": CLAUDE_OPUS,
        "temperature": 0.4,
        "is_coding_agent": True,
        "memory_config": {
            "include_mandates": True,
        },
    },
    {
        "slug": "analyst",
        "name": "Code Analyst",
        "description": "Analyzes code structure and patterns",
        "system_prompt": (
            "You are a code analysis agent.\n\n"
            "Analyze code to understand:\n"
            "- Architecture and structure\n"
            "- Dependencies and relationships\n"
            "- Patterns and anti-patterns\n"
            "- Potential improvements\n\n"
            "Be thorough in analysis but focused in recommendations."
        ),
        "primary_model_id": GEMINI_FLASH,
        "fallback_models": [CLAUDE_SONNET],
        "temperature": 0.4,
        "is_coding_agent": False,
    },
    {
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
    },
    {
        "slug": "explorer",
        "name": "Codebase Explorer",
        "description": "Fast codebase exploration and search synthesis",
        "system_prompt": (
            "You are a codebase exploration agent.\n\n"
            "Search, read, and synthesize codebase information to answer questions about:\n"
            "- Where specific functionality lives\n"
            "- How features are implemented\n"
            "- What patterns are used\n"
            "- Dependencies between modules\n\n"
            "Be thorough in searching but concise in responses."
        ),
        "primary_model_id": GEMINI_FLASH,
        "fallback_models": [CLAUDE_SONNET],
        "temperature": 0.2,
        "is_coding_agent": False,
    },
    {
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
    },
    {
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
    },
    {
        "slug": "qa",
        "name": "QA Supervisor",
        "description": "Reviews task execution quality and determines pass/fail",
        "system_prompt": (
            "You are a QA supervisor agent. You review the overall quality of task "
            "execution and make final pass/fail determinations.\n\n"
            "Review criteria:\n"
            "- All subtasks completed and passing\n"
            "- Code quality meets standards\n"
            "- No regressions introduced\n"
            "- Verify commands all passing\n"
            "- Scope discipline maintained (no feature creep)\n\n"
            "Verdicts:\n"
            "- PASS: Task meets all criteria\n"
            "- FAIL: Specific issues that must be addressed\n"
            "- PARTIAL: Some subtasks pass, others need work\n\n"
            "Be thorough but efficient. Block only on real issues."
        ),
        "primary_model_id": CLAUDE_OPUS,
        "fallback_models": [CLAUDE_SONNET],
        "escalation_model_id": CLAUDE_OPUS,
        "temperature": 0.2,
        "is_coding_agent": False,
        "memory_config": {
            "include_mandates": True,
            "include_guardrails": True,
        },
    },
    {
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
        "memory_config": {
            "include_mandates": False,
            "include_guardrails": False,
            "continuity_enabled": False,
        },
    },
]
