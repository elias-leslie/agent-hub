"""Agent registry with type enum and factory functions.

Provides:
- AgentType: Enum of all available agent types
- get_agent(): Factory to instantiate agents by type
- get_prompt(): Load prompt text by agent type
"""

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.base import AgentConfig, BaseAgent

# Path to prompts directory
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


class AgentType(str, Enum):
    """Available agent types.

    Each type corresponds to a prompt file in prompts/{type}.md
    """

    CODER = "coder"
    PLANNER = "planner"
    REVIEWER = "reviewer"
    FIXER = "fixer"

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
        PlannerAgent,
        ReviewerAgent,
    )

    if isinstance(agent_type, str):
        agent_type = AgentType.from_string(agent_type)

    config = config or AgentConfig()

    agent_map = {
        AgentType.CODER: CoderAgent,
        AgentType.PLANNER: PlannerAgent,
        AgentType.REVIEWER: ReviewerAgent,
        AgentType.FIXER: FixerAgent,
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
    descriptions = {
        AgentType.CODER: "Implements features and fixes bugs",
        AgentType.PLANNER: "Creates implementation plans and analyzes tasks",
        AgentType.REVIEWER: "Reviews code for quality and security",
        AgentType.FIXER: "Diagnoses and fixes errors",
    }

    return [{"type": t.value, "description": descriptions.get(t, "")} for t in AgentType]


# Safety directive for autonomous agents
_SAFETY_DIRECTIVE: str | None = None


def get_safety_directive() -> str:
    """Load the safety directive for autonomous agents.

    Returns:
        The safety directive text from prompts/safety_directive.md
    """
    global _SAFETY_DIRECTIVE
    if _SAFETY_DIRECTIVE is None:
        directive_path = PROMPTS_DIR / "safety_directive.md"
        if directive_path.exists():
            _SAFETY_DIRECTIVE = directive_path.read_text()
        else:
            # Fallback minimal directive
            _SAFETY_DIRECTIVE = (
                "# SAFETY DIRECTIVE\n"
                "You are operating autonomously. Exercise caution.\n"
                "Do not execute destructive commands without verification.\n"
            )
    return _SAFETY_DIRECTIVE


def inject_safety_directive(prompt: str, is_autonomous: bool = False) -> str:
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

    directive = get_safety_directive()
    return f"{directive}\n\n---\n\n{prompt}"
