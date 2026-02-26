"""Push notification tool definition."""

from __future__ import annotations

from app.services.tools.base import Tool

SEND_PUSH_TOOL = Tool(
    name="send_push",
    description=(
        "Send a push notification to the human's devices. Use this to proactively "
        "reach out when something needs attention — task failures, quality issues, "
        "blocked work, or anything that warrants interrupting their flow. "
        "Be thoughtful: only push when it matters."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short notification title (e.g., 'Build failing on main')",
            },
            "body": {
                "type": "string",
                "description": "Notification body — what happened, what it means, what you recommend",
            },
            "url": {
                "type": "string",
                "description": "Optional deep-link URL to open when tapped",
            },
            "severity": {
                "type": "string",
                "enum": ["info", "warning", "error", "critical"],
                "description": "Notification severity (default: info)",
                "default": "info",
            },
            "tag": {
                "type": "string",
                "description": "Optional dedup tag — same tag replaces previous notification",
            },
        },
        "required": ["title", "body"],
    },
)
