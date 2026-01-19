"""Base agent class and shared constants.

All agents inherit from BaseAgent which provides:
- Prompt loading from prompts/ directory
- Common configuration
- Execution interface
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# Path to prompts directory (relative to backend/)
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


@dataclass
class AgentConfig:
    """Configuration for agent execution."""

    provider: Literal["claude", "gemini"] = "claude"
    model: str | None = None
    max_tokens: int = 64000
    temperature: float = 1.0
    thinking_level: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """Abstract base class for all agents.

    Agents load their system prompt from prompts/{agent_type}.md
    and provide an execution interface.
    """

    # Subclasses must set this to match their prompt file
    agent_type: str = ""

    def __init__(self, config: AgentConfig | None = None):
        """Initialize agent with optional config override."""
        self.config = config or AgentConfig()
        self._prompt: str | None = None

    @property
    def system_prompt(self) -> str:
        """Load and cache the system prompt from prompts/ directory."""
        if self._prompt is None:
            self._prompt = self._load_prompt()
        return self._prompt

    def _load_prompt(self) -> str:
        """Load prompt from prompts/{agent_type}.md file."""
        if not self.agent_type:
            raise ValueError(f"{self.__class__.__name__} must set agent_type")

        prompt_path = PROMPTS_DIR / f"{self.agent_type}.md"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt not found: {prompt_path}")

        return prompt_path.read_text()

    @abstractmethod
    async def execute(self, task: str, context: dict[str, Any] | None = None) -> str:
        """Execute the agent on a task.

        Args:
            task: The task description or user message
            context: Optional context dict (files, history, etc.)

        Returns:
            The agent's response
        """
        pass


class CoderAgent(BaseAgent):
    """Coding agent for implementing features and fixing bugs."""

    agent_type = "coder"

    async def execute(self, task: str, context: dict[str, Any] | None = None) -> str:
        """Execute coding task."""
        # Implementation delegated to AgentRunner
        raise NotImplementedError("Use AgentRunner for execution")


class PlannerAgent(BaseAgent):
    """Planning agent for analyzing tasks and creating implementation plans."""

    agent_type = "planner"

    async def execute(self, task: str, context: dict[str, Any] | None = None) -> str:
        """Execute planning task."""
        raise NotImplementedError("Use AgentRunner for execution")


class ReviewerAgent(BaseAgent):
    """Review agent for code review and quality assessment."""

    agent_type = "reviewer"

    async def execute(self, task: str, context: dict[str, Any] | None = None) -> str:
        """Execute review task."""
        raise NotImplementedError("Use AgentRunner for execution")


class FixerAgent(BaseAgent):
    """Fixer agent for diagnosing and fixing errors."""

    agent_type = "fixer"

    async def execute(self, task: str, context: dict[str, Any] | None = None) -> str:
        """Execute fix task."""
        raise NotImplementedError("Use AgentRunner for execution")
