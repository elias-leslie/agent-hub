"""Agent Runner service for autonomous task execution.

Provides agentic completion with tool execution loops:
- For Claude: Uses enable_programmatic_tools (code_execution sandbox)
- For Gemini: Executes provided tool handlers in a loop

The agent runner handles the turn-based conversation loop, executing
tool calls and feeding results back until the task is complete.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from app.adapters.base import Message, ProviderError
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.constants import CLAUDE_SONNET, GEMINI_FLASH
from app.services.container_manager import ContainerManager
from app.services.tools.base import Tool, ToolCall, ToolHandler, ToolRegistry, ToolResult

logger = logging.getLogger(__name__)

# Maximum turns for agentic loop (safety limit)
MAX_AGENT_TURNS = 20


@dataclass
class AgentProgress:
    """Progress update from agent execution."""

    turn: int
    status: str  # "running", "tool_use", "thinking", "complete", "error"
    message: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    thinking: str | None = None


@dataclass
class AgentResult:
    """Result from agent execution."""

    agent_id: str
    status: str  # "success", "error", "max_turns"
    content: str
    provider: str
    model: str
    turns: int
    input_tokens: int
    output_tokens: int
    thinking_tokens: int = 0
    tool_calls_count: int = 0
    error: str | None = None
    progress_log: list[AgentProgress] = field(default_factory=list)
    container_id: str | None = None  # For Claude code execution


@dataclass
class AgentConfig:
    """Configuration for agent execution."""

    provider: Literal["claude", "gemini"] = "claude"
    model: str | None = None
    system_prompt: str | None = None
    temperature: float = 1.0
    max_turns: int = MAX_AGENT_TURNS
    # Extended thinking
    thinking_level: str | None = None  # minimal/low/medium/high/ultrathink
    enable_code_execution: bool = True  # Use programmatic tools
    container_id: str | None = None  # Reuse existing container
    working_dir: str | None = None  # Working directory for agent execution
    # Gemini-specific
    tools: list[Tool] | None = None
    tool_handler: ToolHandler | None = None


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

        try:
            if provider == "claude" and config.enable_code_execution:
                # Claude with code execution - handles tools internally
                result = await self._run_claude_code_execution(
                    messages=messages,
                    config=config,
                    result=result,
                    progress_callback=progress_callback,
                )
            elif provider == "gemini":
                # Gemini with external tool execution
                # Use standard tools if none provided
                if not config.tools or not config.tool_handler:
                    from app.services.tools.sandboxed_executor import (
                        create_sandboxed_handler,
                        get_standard_tools,
                    )

                    config.tools = config.tools or get_standard_tools()
                    config.tool_handler = config.tool_handler or create_sandboxed_handler(
                        config.working_dir
                    )

                result = await self._run_gemini_with_tools(
                    messages=messages,
                    config=config,
                    result=result,
                    progress_callback=progress_callback,
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

        logger.info(
            f"Agent {agent_id} completed: status={result.status}, "
            f"turns={result.turns}, tokens={result.input_tokens + result.output_tokens}"
        )

        return result

    def _get_default_model(self, provider: str) -> str:
        """Get default model for provider."""
        if provider == "claude":
            return CLAUDE_SONNET
        elif provider == "gemini":
            return GEMINI_FLASH
        else:
            return "unknown"

    async def _run_claude_code_execution(
        self,
        messages: list[Message],
        config: AgentConfig,
        result: AgentResult,
        progress_callback: Any | None = None,
    ) -> AgentResult:
        """
        Run Claude with code execution enabled.

        Claude handles tool execution internally via its sandbox.
        We just need to continue the conversation if it stops for tool_use.
        """
        adapter = self._get_adapter("claude")
        model = config.model or CLAUDE_SONNET

        # Check for existing container to reuse
        container_id = config.container_id
        if container_id:
            container = self._container_manager.get(container_id)
            if not container:
                container_id = None  # Container expired, don't reuse

        turn = 0
        while turn < config.max_turns:
            turn += 1
            result.turns = turn

            # Report progress
            progress = AgentProgress(
                turn=turn,
                status="running",
                message=f"Turn {turn}: sending to Claude",
            )
            result.progress_log.append(progress)
            if progress_callback:
                await progress_callback(progress)

            try:
                # Make completion request with code execution
                completion = await adapter.complete(
                    messages=messages,
                    model=model,
                    temperature=config.temperature,
                    thinking_level=config.thinking_level,
                    tools=None,  # Code execution provides tools
                    enable_programmatic_tools=True,
                    container_id=container_id,
                    working_dir=config.working_dir,
                )

                # Track tokens
                result.input_tokens += completion.input_tokens
                result.output_tokens += completion.output_tokens
                if completion.thinking_tokens:
                    result.thinking_tokens += completion.thinking_tokens

                # Track container
                if completion.container:
                    container_id = completion.container.id
                    result.container_id = container_id
                    self._container_manager.register(
                        container_id=container_id,
                        expires_at=completion.container.expires_at,
                        session_id=result.agent_id,
                    )

                # Check stop reason
                if completion.finish_reason == "end_turn":
                    # Agent completed
                    result.status = "success"
                    result.content = completion.content
                    progress = AgentProgress(
                        turn=turn,
                        status="complete",
                        message="Agent completed task",
                    )
                    result.progress_log.append(progress)
                    if progress_callback:
                        await progress_callback(progress)
                    break

                elif completion.finish_reason == "tool_use":
                    # Claude called tools via code execution
                    result.tool_calls_count += len(completion.tool_calls or [])

                    # Add assistant's response to conversation
                    # The tool results are already in the response from code_execution
                    messages.append(Message(role="assistant", content=completion.content))

                    progress = AgentProgress(
                        turn=turn,
                        status="tool_use",
                        message=f"Executed {len(completion.tool_calls or [])} tool(s)",
                        tool_calls=[
                            {"name": tc.name, "input": tc.input}
                            for tc in (completion.tool_calls or [])
                        ],
                    )
                    result.progress_log.append(progress)
                    if progress_callback:
                        await progress_callback(progress)

                    # Continue conversation - Claude will see tool results
                    messages.append(
                        Message(role="user", content="Continue based on the tool results.")
                    )

                elif completion.finish_reason == "max_tokens":
                    # Hit token limit
                    result.status = "error"
                    result.error = "Response truncated due to max_tokens"
                    result.content = completion.content
                    break

                else:
                    # Unknown stop reason
                    result.content = completion.content
                    if turn == config.max_turns:
                        result.status = "max_turns"
                        result.error = f"Reached maximum turns ({config.max_turns})"
                    else:
                        # Keep going
                        messages.append(Message(role="assistant", content=completion.content))
                        messages.append(Message(role="user", content="Please continue."))

            except ProviderError as e:
                result.status = "error"
                result.error = str(e)
                break

        if result.status == "running":
            result.status = "max_turns"
            result.error = f"Reached maximum turns ({config.max_turns})"

        return result

    async def _run_gemini_with_tools(
        self,
        messages: list[Message],
        config: AgentConfig,
        result: AgentResult,
        progress_callback: Any | None = None,
    ) -> AgentResult:
        """
        Run Gemini with external tool execution.

        Unlike Claude, Gemini doesn't have code execution sandbox.
        We execute tools locally using the provided ToolHandler.
        """
        from app.services.tools.gemini_tools import format_tools_for_api

        adapter = self._get_adapter("gemini")
        model = config.model or GEMINI_FLASH

        # Build tool registry and convert to Gemini API format
        registry = ToolRegistry(tools=config.tools or [])
        tool_defs = format_tools_for_api(registry)
        handler = config.tool_handler

        if not handler:
            raise ValueError("tool_handler required for Gemini with tools")

        turn = 0
        while turn < config.max_turns:
            turn += 1
            result.turns = turn

            progress = AgentProgress(
                turn=turn,
                status="running",
                message=f"Turn {turn}: sending to Gemini",
            )
            result.progress_log.append(progress)
            if progress_callback:
                await progress_callback(progress)

            try:
                # Make completion request with tools
                completion = await adapter.complete(
                    messages=messages,
                    model=model,
                    temperature=config.temperature,
                    tools=tool_defs,
                )

                # Track tokens
                result.input_tokens += completion.input_tokens
                result.output_tokens += completion.output_tokens

                # Check for tool calls
                if completion.tool_calls:
                    result.tool_calls_count += len(completion.tool_calls)

                    # Execute each tool
                    tool_results: list[ToolResult] = []
                    for tc in completion.tool_calls:
                        tool_call = ToolCall(
                            id=tc.id,
                            name=tc.name,
                            input=tc.input,
                        )

                        progress = AgentProgress(
                            turn=turn,
                            status="tool_use",
                            message=f"Executing tool: {tc.name}",
                            tool_calls=[{"name": tc.name, "input": tc.input}],
                        )
                        result.progress_log.append(progress)
                        if progress_callback:
                            await progress_callback(progress)

                        # Execute via handler
                        tool_result = await handler.execute(tool_call)
                        tool_results.append(tool_result)

                    # Add assistant response with tool calls
                    messages.append(Message(role="assistant", content=completion.content))

                    # Add tool results as user message
                    tool_result_content = "\n".join(
                        f"Tool '{r.tool_use_id}' result: {r.content}" for r in tool_results
                    )
                    messages.append(
                        Message(
                            role="user",
                            content=f"Tool execution results:\n{tool_result_content}\n\nContinue based on these results.",
                        )
                    )

                    progress = AgentProgress(
                        turn=turn,
                        status="tool_use",
                        message=f"Executed {len(tool_results)} tool(s)",
                        tool_results=[
                            {"id": r.tool_use_id, "content": r.content[:200]} for r in tool_results
                        ],
                    )
                    result.progress_log.append(progress)
                    if progress_callback:
                        await progress_callback(progress)

                else:
                    # No tool calls - agent is done
                    result.status = "success"
                    result.content = completion.content
                    progress = AgentProgress(
                        turn=turn,
                        status="complete",
                        message="Agent completed task",
                    )
                    result.progress_log.append(progress)
                    if progress_callback:
                        await progress_callback(progress)
                    break

            except ProviderError as e:
                result.status = "error"
                result.error = str(e)
                break

        if result.status == "running":
            result.status = "max_turns"
            result.error = f"Reached maximum turns ({config.max_turns})"

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
