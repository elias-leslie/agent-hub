"""Coordination and oversight support agents.

Includes: supervisor, qa
"""

from app.constants import CLAUDE_OPUS, CLAUDE_SONNET, GEMINI_FLASH

_SUPERVISOR: dict[str, object] = {
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
}

_QA: dict[str, object] = {
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
}

COORDINATION_AGENTS: list[dict[str, object]] = [_SUPERVISOR, _QA]
