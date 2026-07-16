"""Specialized code review maker-checker pattern."""

from .maker_checker import MakerChecker
from .subagent import SubagentConfig


class CodeReviewPattern(MakerChecker):
    """Specialized maker-checker for code generation and review."""

    def __init__(
        self,
        maker_provider: str = "kimi-code",
        checker_provider: str = "gemini",
        max_iterations: int = 2,
        project_id: str | None = None,
    ):
        """Initialize code review pattern.

        Uses different providers for maker and checker by default
        to get diverse perspectives.
        """
        maker_config = SubagentConfig(
            name="code_generator",
            provider=maker_provider,
            project_id=project_id,
            agent_slug="coder",
            system_prompt="""You are an expert programmer. Generate clean, well-documented code.
Follow best practices and include error handling where appropriate.""",
            temperature=0.7,
        )

        checker_config = SubagentConfig(
            name="code_reviewer",
            provider=checker_provider,
            project_id=project_id,
            agent_slug="reviewer",
            system_prompt="""You are a senior code reviewer. Review code for:
1. Correctness - Does it solve the problem?
2. Security - Any vulnerabilities?
3. Performance - Any obvious inefficiencies?
4. Readability - Is it clear and maintainable?
5. Best practices - Does it follow conventions?

Format response as:
DECISION: [APPROVED or NEEDS_REVISION]
CONFIDENCE: [0.0-1.0]
ISSUES:
- [specific issues]
SUGGESTIONS:
- [specific improvements]""",
            temperature=0.3,
        )

        super().__init__(
            maker_config=maker_config,
            checker_config=checker_config,
            max_iterations=max_iterations,
        )
