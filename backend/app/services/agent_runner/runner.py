"""Agent Runner orchestration."""

import logging
import uuid
from typing import Any

from app.adapters.base import Message, ProviderError
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.constants import CLAUDE_SONNET, GEMINI_FLASH
from app.db import get_db
from app.services.container_manager import ContainerManager

from .claude_executor import run_claude_code_execution
from .debug_logging import log_agent_input, log_final_output
from .gemini_executor import run_gemini_with_tools
from .models import AgentConfig, AgentProgress, AgentResult

logger = logging.getLogger(__name__)


class AgentRunner:
    """
    Runs an agent to completion on a task.

    Handles the agentic loop:
    1. Send task to model
    2. If tool calls returned, execute them
    3. Feed results back to model
    4. Repeat until model stops calling tools

    For Claude with code_execution enabled, the model can write
    and execute code that calls tools programmatically.

    For Gemini, tools must be provided along with a ToolHandler
    to execute them.
    """

    def __init__(self) -> None:
        """Initialize agent runner."""
        self._claude_adapter: ClaudeAdapter | None = None
        self._gemini_adapter: GeminiAdapter | None = None
        self._container_manager = ContainerManager()

    def _get_adapter(self, provider: str) -> ClaudeAdapter | GeminiAdapter:
        """Get cached adapter for provider."""
        if provider == "claude":
            if self._claude_adapter is None:
                self._claude_adapter = ClaudeAdapter()
            return self._claude_adapter
        elif provider == "gemini":
            if self._gemini_adapter is None:
                self._gemini_adapter = GeminiAdapter()
            return self._gemini_adapter
        else:
            raise ValueError(f"Unknown provider: {provider}")

    def _get_default_model(self, provider: str) -> str:
        """Get default model for provider."""
        if provider == "claude":
            return CLAUDE_SONNET
        elif provider == "gemini":
            return GEMINI_FLASH
        else:
            return "unknown"

    async def run(
        self,
        task: str,
        config: AgentConfig | None = None,
        progress_callback: Any | None = None,
    ) -> AgentResult:
        """
        Run an agent on a task.

        Args:
            task: The task description for the agent
            config: Agent configuration (provider, model, tools, etc.)
            progress_callback: Optional async callback for progress updates

        Returns:
            AgentResult with final output and execution details
        """
        config = config or AgentConfig()
        agent_id = str(uuid.uuid4())
        provider = config.provider

        logger.info(f"Starting agent {agent_id} with provider={provider}")

        # Debug log the full input
        log_agent_input(
            agent_id=agent_id,
            system_prompt=config.system_prompt,
            task=task,
            model=config.model or self._get_default_model(provider),
            provider=provider,
        )

        # Initialize result tracking
        result = AgentResult(
            agent_id=agent_id,
            status="running",
            content="",
            provider=provider,
            model=config.model or self._get_default_model(provider),
            turns=0,
            input_tokens=0,
            output_tokens=0,
        )

        # Build initial messages
        messages: list[Message] = []
        if config.system_prompt:
            messages.append(Message(role="system", content=config.system_prompt))
        messages.append(Message(role="user", content=task))

        # Create real DB session for tracking
        async for db in get_db():
            try:
                if provider == "claude" and config.enable_code_execution:
                    # Claude with code execution - handles tools internally
                    if self._claude_adapter is None:
                        self._claude_adapter = ClaudeAdapter()
                    result = await run_claude_code_execution(
                        messages=messages,
                        config=config,
                        result=result,
                        adapter=self._claude_adapter,
                        container_manager=self._container_manager,
                        progress_callback=progress_callback,
                        db=db,
                    )
                elif provider == "gemini":
                    # Gemini with external tool execution
                    # Use standard tools if none provided
                    if not config.tools or not config.tool_handler:
                        from app.services.tools.direct_executor import (
                            create_direct_handler,
                            get_standard_tools,
                        )

                        config.tools = config.tools or get_standard_tools()
                        config.tool_handler = config.tool_handler or create_direct_handler(
                            config.working_dir
                        )

                    if self._gemini_adapter is None:
                        self._gemini_adapter = GeminiAdapter()
                    result = await run_gemini_with_tools(
                        messages=messages,
                        config=config,
                        result=result,
                        adapter=self._gemini_adapter,
                        progress_callback=progress_callback,
                        db=db,
                    )
                else:
                    # Simple completion (no tool loop)
                    result = await self._run_simple_completion(
                        messages=messages,
                        config=config,
                        result=result,
                        progress_callback=progress_callback,
                    )

            except Exception as e:
                logger.exception(f"Agent {agent_id} failed")
                result.status = "error"
                result.error = str(e)
            break  # Only need one iteration

        logger.info(
            f"Agent {agent_id} completed: status={result.status}, "
            f"turns={result.turns}, tokens={result.input_tokens + result.output_tokens}, "
            f"session={result.session_id}"
        )

        # Debug log final output
        log_final_output(
            agent_id=agent_id,
            status=result.status,
            content=result.content,
            turns=result.turns,
            tool_calls_count=result.tool_calls_count,
        )

        return result

    async def _run_simple_completion(
        self,
        messages: list[Message],
        config: AgentConfig,
        result: AgentResult,
        progress_callback: Any | None = None,
    ) -> AgentResult:
        """
        Run a simple completion without tool loop.

        Used when no tools are configured or code execution is disabled.
        """
        adapter = self._get_adapter(config.provider)
        model = config.model or self._get_default_model(config.provider)

        result.turns = 1

        progress = AgentProgress(
            turn=1,
            status="running",
            message=f"Sending to {config.provider}",
        )
        result.progress_log.append(progress)
        if progress_callback:
            await progress_callback(progress)

        try:
            if config.provider == "claude":
                completion = await adapter.complete(
                    messages=messages,
                    model=model,
                    temperature=config.temperature,
                    thinking_level=config.thinking_level,
                )
            else:
                completion = await adapter.complete(
                    messages=messages,
                    model=model,
                    temperature=config.temperature,
                )

            result.input_tokens = completion.input_tokens
            result.output_tokens = completion.output_tokens
            if completion.thinking_tokens:
                result.thinking_tokens = completion.thinking_tokens

            result.status = "success"
            result.content = completion.content

            progress = AgentProgress(
                turn=1,
                status="complete",
                message="Completion received",
            )
            result.progress_log.append(progress)
            if progress_callback:
                await progress_callback(progress)

        except ProviderError as e:
            result.status = "error"
            result.error = str(e)

        return result


# Singleton instance
_agent_runner: AgentRunner | None = None


def get_agent_runner() -> AgentRunner:
    """Get singleton AgentRunner instance."""
    global _agent_runner
    if _agent_runner is None:
        _agent_runner = AgentRunner()
    return _agent_runner
