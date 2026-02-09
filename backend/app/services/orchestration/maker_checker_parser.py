"""Response parser for maker-checker pattern."""

from typing import Any


def parse_checker_response(content: str) -> dict[str, Any]:
    """Parse checker response into structured data.

    Expected format:
        DECISION: [APPROVED or NEEDS_REVISION]
        CONFIDENCE: [0.0-1.0]
        ISSUES:
        - [issue 1]
        - [issue 2]
        SUGGESTIONS:
        - [suggestion 1]
        - [suggestion 2]

    Args:
        content: Raw checker response text.

    Returns:
        Dictionary with approved, confidence, issues, and suggestions.
    """
    result: dict[str, Any] = {
        "approved": False,
        "confidence": 0.5,
        "issues": [],
        "suggestions": [],
    }

    lines = content.strip().split("\n")
    current_section: str | None = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("DECISION:"):
            decision = line.replace("DECISION:", "").strip().upper()
            result["approved"] = decision == "APPROVED"
        elif line.startswith("CONFIDENCE:"):
            try:
                conf = float(line.replace("CONFIDENCE:", "").strip())
                result["confidence"] = max(0.0, min(1.0, conf))
            except ValueError:
                pass
        elif line.startswith("ISSUES:"):
            current_section = "issues"
        elif line.startswith("SUGGESTIONS:"):
            current_section = "suggestions"
        elif line.startswith("- ") and current_section:
            item = line[2:].strip()
            if item:
                result[current_section].append(item)

    return result


def build_default_checker_prompt() -> str:
    """Build default system prompt for checker agent.

    Returns:
        System prompt instructing the checker how to format responses.
    """
    return """You are a verification agent. Your role is to:
1. Review the output provided by another agent
2. Identify any issues, errors, or problems
3. Provide an approval decision (APPROVED or NEEDS_REVISION)
4. List specific issues if not approved
5. Suggest improvements if applicable

Format your response as:
DECISION: [APPROVED or NEEDS_REVISION]
CONFIDENCE: [0.0-1.0]
ISSUES:
- [issue 1]
- [issue 2]
SUGGESTIONS:
- [suggestion 1]
- [suggestion 2]

Be thorough but fair. Only reject if there are genuine problems."""
