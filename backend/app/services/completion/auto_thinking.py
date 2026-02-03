"""Auto-thinking detection for completion requests."""

from typing import Any

# Thinking trigger keywords
THINKING_TRIGGERS = [
    "ultrathink",
    "think hard",
    "think carefully",
    "think step by step",
    "analyze",
    "evaluate",
    "compare",
    "explain why",
    "reason",
    "think through",
    "consider carefully",
    "debug",
    "review code",
    "find the bug",
    "what's wrong",
    "refactor",
    "multi-step",
    "complex",
    "edge cases",
]


def extract_text_content(content: str | list[dict[str, Any]]) -> str:
    """Extract text from message content."""
    if isinstance(content, str):
        return content
    texts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            texts.append(block.get("text", ""))
        elif isinstance(block, str):
            texts.append(block)
    return " ".join(texts)


def should_enable_thinking(messages: list[dict[str, Any]]) -> bool:
    """Detect if request would benefit from extended thinking."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            text_content = extract_text_content(msg.get("content", ""))
            content_lower = text_content.lower()
            for trigger in THINKING_TRIGGERS:
                if trigger in content_lower:
                    return True
            if any(f"{i}." in text_content for i in range(1, 10)):
                return True
            break
    return False
