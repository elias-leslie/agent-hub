"""Agent registry with type enum and factory functions.

Provides:
- AgentType: Enum of all available agent types
- get_agent(): Factory to instantiate agents by type
- get_prompt(): Load prompt text by agent type
"""

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.base import AgentConfig, BaseAgent

# Path to prompts directory
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class AgentType(StrEnum):
    """Available agent types.

    Each type corresponds to a prompt file in prompts/{type}.md
    """

    CODER = "coder"
    PLANNER = "planner"
    REVIEWER = "reviewer"
    FIXER = "fixer"
    IDEATOR_PUBLIC = "ideator-public"

    @classmethod
    def from_string(cls, value: str) -> "AgentType":
        """Convert string to AgentType, case-insensitive."""
        try:
            return cls(value.lower())
        except ValueError as err:
            valid = ", ".join(t.value for t in cls)
            raise ValueError(f"Unknown agent type: {value}. Valid types: {valid}") from err


def get_prompt(agent_type: AgentType | str) -> str:
    """Load prompt text for an agent type.

    Args:
        agent_type: AgentType enum or string name

    Returns:
        The prompt text from prompts/{type}.md

    Raises:
        FileNotFoundError: If prompt file doesn't exist
    """
    if isinstance(agent_type, str):
        agent_type = AgentType.from_string(agent_type)

    prompt_path = PROMPTS_DIR / f"{agent_type.value}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")

    return prompt_path.read_text()


def get_agent(
    agent_type: AgentType | str,
    config: "AgentConfig | None" = None,
) -> "BaseAgent":
    """Factory function to get an agent by type.

    Args:
        agent_type: AgentType enum or string name
        config: Optional configuration override

    Returns:
        Instantiated agent of the requested type

    Raises:
        ValueError: If agent type is unknown
    """
    # Import here to avoid circular imports
    from agents.base import (
        AgentConfig,
        CoderAgent,
        FixerAgent,
        IdeatorPublicAgent,
        PlannerAgent,
        ReviewerAgent,
    )

    if isinstance(agent_type, str):
        agent_type = AgentType.from_string(agent_type)

    config = config or AgentConfig()

    agent_map: dict[AgentType, type[BaseAgent]] = {
        AgentType.CODER: CoderAgent,
        AgentType.PLANNER: PlannerAgent,
        AgentType.REVIEWER: ReviewerAgent,
        AgentType.FIXER: FixerAgent,
        AgentType.IDEATOR_PUBLIC: IdeatorPublicAgent,
    }

    agent_class = agent_map.get(agent_type)
    if agent_class is None:
        raise ValueError(f"No agent implementation for type: {agent_type}")

    return agent_class(config)


def list_agents() -> list[dict[str, str]]:
    """List all available agents with their descriptions.

    Returns:
        List of dicts with 'type' and 'description' keys
    """
    descriptions: dict[AgentType, str] = {
        AgentType.CODER: "Implements features and fixes bugs",
        AgentType.PLANNER: "Creates implementation plans and analyzes tasks",
        AgentType.REVIEWER: "Reviews code for quality and security",
        AgentType.FIXER: "Diagnoses and fixes errors",
        AgentType.IDEATOR_PUBLIC: "Helps players share game improvement ideas in a friendly, age-appropriate conversation",
    }

    return [{"type": t.value, "description": descriptions.get(t, "")} for t in AgentType]


# Safety directive for autonomous agents — loaded from DB prompts table.
# Slug: "safety-directive". Managed via Agent Hub prompt API/UI.
_SAFETY_DIRECTIVE: str | None = None

SAFETY_DIRECTIVE_SLUG = "safety-directive"


async def get_safety_directive() -> str:
    """Load the safety directive for autonomous agents from the database.

    The safety directive is stored in the prompts table with slug
    "safety-directive". It must exist — there is no hardcoded fallback.
    Use the Agent Hub prompt API to create/update it.

    Returns:
        The safety directive text

    Raises:
        RuntimeError: If the safety directive is not found in the database
    """
    global _SAFETY_DIRECTIVE
    if _SAFETY_DIRECTIVE is not None:
        return _SAFETY_DIRECTIVE

    from app.db import async_session
    from app.services.prompt_service import get_prompt_by_slug

    async with async_session() as db:
        prompt = await get_prompt_by_slug(db, SAFETY_DIRECTIVE_SLUG)
        if not prompt:
            raise RuntimeError(
                f"Safety directive not found in prompts table "
                f"(slug='{SAFETY_DIRECTIVE_SLUG}'). "
                f"Create it via the prompt API: "
                f"POST /prompts with slug='{SAFETY_DIRECTIVE_SLUG}'"
            )
        _SAFETY_DIRECTIVE = prompt.content
        return _SAFETY_DIRECTIVE


async def inject_safety_directive(prompt: str, is_autonomous: bool = False) -> str:
    """Inject safety directive into a prompt for autonomous agents.

    Args:
        prompt: The original system prompt
        is_autonomous: Whether this is an autonomous agent operation

    Returns:
        The prompt with safety directive prepended (if autonomous),
        or the original prompt (if not autonomous)
    """
    if not is_autonomous:
        return prompt

    directive = await get_safety_directive()
    return f"{directive}\n\n---\n\n{prompt}"
