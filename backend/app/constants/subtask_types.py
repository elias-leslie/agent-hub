"""Canonical subtask type definitions for task routing."""

from __future__ import annotations

SUBTASK_TYPE_DESCRIPTIONS: dict[str, str] = {
    "backend": "Server-side logic, APIs, services, database-backed flows",
    "frontend": "UI components, pages, client-side behavior",
    "ui-design": "Visual polish, layout, animation, design system work",
    "refactor": "Code restructuring without behavior change",
    "bug-fix": "Diagnosing and fixing defects",
    "test": "Unit/integration/e2e testing work",
    "performance": "Optimization, caching, and query tuning",
    "config": "Configuration, environment, and build setup",
    "devops": "CI/CD, deployment, and infrastructure",
    "database": "Schema changes, migrations, and data modeling",
    "image-gen": "Image generation requests and asset prompts",
    "game-design": "Gameplay systems and balancing design work",
    "design-review": "UI/UX review and design critique",
    "exploration": "Codebase exploration and technical investigation",
}

# Keep declaration order stable for tool schemas and prompt generation.
SUBTASK_TYPES: tuple[str, ...] = tuple(SUBTASK_TYPE_DESCRIPTIONS.keys())


def format_subtask_types_markdown() -> str:
    """Return a stable bullet list for prompts/docs."""
    return "\n".join(
        f"- {subtask_type}: {description}"
        for subtask_type, description in SUBTASK_TYPE_DESCRIPTIONS.items()
    )

