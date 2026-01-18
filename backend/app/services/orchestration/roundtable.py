"""Roundtable multi-agent collaboration.

Ported from SummitFlow. Enables Claude and Gemini agents to collaborate
on tasks, with turn-taking, targeting, and shared context.
"""

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from opentelemetry.trace import SpanKind, Status, StatusCode

from app.adapters.base import Message
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.services.memory.context_injector import build_global_context
from app.services.memory.service import MemoryScope
from app.services.telemetry import get_current_trace_id, get_tracer

logger = logging.getLogger(__name__)

# Type aliases
AgentType = Literal["claude", "gemini"]
TargetAgent = Literal["claude", "gemini", "both"]


@dataclass
class RoundtableMessage:
    """A message in a roundtable session."""

    id: str
    role: Literal["user", "claude", "gemini", "system"]
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    tokens_used: int = 0
    model: str | None = None

    @classmethod
    def create(
        cls,
        role: Literal["user", "claude", "gemini", "system"],
        content: str,
        tokens_used: int = 0,
        model: str | None = None,
    ) -> "RoundtableMessage":
        """Create a new message."""
        import uuid

        return cls(
            id=str(uuid.uuid4())[:8],
            role=role,
            content=content,
            tokens_used=tokens_used,
            model=model,
        )


@dataclass
class RoundtableSession:
    """A roundtable collaboration session."""

    id: str
    project_id: str
    mode: Literal["quick", "deliberation"] = "quick"
    tools_enabled: bool = True
    messages: list[RoundtableMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    trace_id: str | None = None
    """OpenTelemetry trace ID for correlation."""
    memory_context: str = ""
    """Pre-fetched memory context for injection into agent prompts."""

    @classmethod
    def create(
        cls,
        project_id: str,
        mode: Literal["quick", "deliberation"] = "quick",
        tools_enabled: bool = True,
    ) -> "RoundtableSession":
        """Create a new session."""
        import uuid

        # Get trace ID from current context if available
        trace_id = get_current_trace_id()
        return cls(
            id=str(uuid.uuid4())[:8],
            project_id=project_id,
            mode=mode,
            tools_enabled=tools_enabled,
            trace_id=trace_id,
        )

    def add_message(self, message: RoundtableMessage) -> None:
        """Add a message to the session."""
        self.messages.append(message)

    def get_context(self, max_messages: int = 20) -> str:
        """Get conversation context as formatted string."""
        recent = self.messages[-max_messages:]
        parts = []
        for msg in recent:
            speaker = msg.role.upper()
            parts.append(f"[{speaker}]: {msg.content}")
        return "\n\n".join(parts)

    @property
    def total_tokens(self) -> int:
        """Total tokens used in session."""
        return sum(m.tokens_used for m in self.messages)


@dataclass
class RoundtableEvent:
    """Event from roundtable streaming."""

    type: Literal["message", "thinking", "tool_call", "error", "done"]
    agent: AgentType | None = None
    content: str = ""
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None
    tokens: int = 0
    error: str | None = None


class RoundtableService:
    """Multi-agent roundtable collaboration service.

    Enables Claude and Gemini to collaborate on tasks:
    - Route messages to specific agent or both
    - Agents see each other's responses
    - Turn-taking in deliberation mode
    - Consensus building
    """

    def __init__(
        self,
        claude_model: str | None = None,
        gemini_model: str | None = None,
    ):
        """Initialize roundtable service.

        Args:
            claude_model: Model for Claude agent.
            gemini_model: Model for Gemini agent.
        """
        from app.constants import CLAUDE_SONNET, GEMINI_FLASH

        self._claude_model = claude_model or CLAUDE_SONNET
        self._gemini_model = gemini_model or GEMINI_FLASH
        self._sessions: dict[str, RoundtableSession] = {}

        # Create adapters
        self._claude_adapter = ClaudeAdapter()
        self._gemini_adapter = GeminiAdapter()

    async def create_session(
        self,
        project_id: str,
        mode: Literal["quick", "deliberation"] = "quick",
        tools_enabled: bool = True,
        use_memory: bool = True,
    ) -> RoundtableSession:
        """Create a new roundtable session.

        Args:
            project_id: Project identifier.
            mode: Collaboration mode (quick or deliberation).
            tools_enabled: Whether agents can use tools.
            use_memory: Whether to inject memory context into agent prompts.
        """
        session = RoundtableSession.create(project_id, mode, tools_enabled)

        # Fetch memory context for the session (GLOBAL scope per decision d3)
        if use_memory:
            try:
                memory_ctx = await build_global_context(
                    scope=MemoryScope.GLOBAL,
                    scope_id=None,
                    task_description=None,
                    max_results=10,
                )
                session.memory_context = memory_ctx
                if memory_ctx:
                    logger.info(
                        f"Injected memory context into roundtable session {session.id} "
                        f"({len(memory_ctx)} chars)"
                    )
            except Exception as e:
                logger.warning(f"Failed to fetch memory context for roundtable: {e}")

        self._sessions[session.id] = session
        logger.info(f"Created roundtable session {session.id} mode={mode}")
        return session

    def get_session(self, session_id: str) -> RoundtableSession | None:
        """Get an existing session."""
        return self._sessions.get(session_id)

    def _build_system_prompt(self, agent: AgentType, memory_context: str = "") -> str:
        """Build system prompt for an agent.

        Args:
            agent: Agent type (claude or gemini).
            memory_context: Pre-fetched memory context to inject.
        """
        name = "Claude" if agent == "claude" else "Gemini"
        base_prompt = f"""You are {name}, participating in a collaborative roundtable discussion.
Other agents may also provide responses. Consider their input when appropriate.
Be concise but thorough. Focus on the task at hand."""

        if memory_context:
            return f"{base_prompt}\n\n{memory_context}"
        return base_prompt

    def _build_prompt(self, message: str, context: str, agent: AgentType) -> str:
        """Build prompt with context for an agent."""
        if not context:
            return message

        other = "Gemini" if agent == "claude" else "Claude"
        return f"""Previous conversation:
{context}

{other} may have already responded above. Consider their input if relevant.

User's message: {message}"""

    async def route_message(
        self,
        session: RoundtableSession,
        message: str,
        target: TargetAgent = "both",
    ) -> AsyncGenerator[RoundtableEvent]:
        """Route a message to agents and stream responses.

        Args:
            session: The roundtable session.
            message: User's message.
            target: Which agent(s) to target.

        Yields:
            RoundtableEvents as agents respond.
        """
        # Add user message to session
        user_msg = RoundtableMessage.create("user", message)
        session.add_message(user_msg)

        context = session.get_context()

        # Route to Claude
        if target in ("claude", "both"):
            async for event in self._call_agent("claude", message, context, session):
                yield event
            # Update context with Claude's response
            context = session.get_context()

        # Route to Gemini
        if target in ("gemini", "both"):
            async for event in self._call_agent("gemini", message, context, session):
                yield event

        yield RoundtableEvent(type="done")

    async def _call_agent(
        self,
        agent: AgentType,
        message: str,
        context: str,
        session: RoundtableSession,
    ) -> AsyncGenerator[RoundtableEvent]:
        """Call a specific agent and stream response."""
        tracer = get_tracer("agent-hub.orchestration.roundtable")
        adapter = self._claude_adapter if agent == "claude" else self._gemini_adapter
        model = self._claude_model if agent == "claude" else self._gemini_model

        # Create a span for this agent call
        with tracer.start_as_current_span(
            f"roundtable.call_agent.{agent}",
            kind=SpanKind.INTERNAL,
            attributes={
                "roundtable.session_id": session.id,
                "roundtable.agent": agent,
                "roundtable.model": model,
                "roundtable.message_length": len(message),
                "roundtable.context_length": len(context),
            },
        ) as span:
            system = self._build_system_prompt(agent, session.memory_context)
            prompt = self._build_prompt(message, context, agent)

            messages = [
                Message(role="system", content=system),
                Message(role="user", content=prompt),
            ]

            try:
                # Stream response
                content_parts: list[str] = []
                total_tokens = 0
                async for event in adapter.stream(messages, model):
                    if event.type == "content":
                        content_parts.append(event.content)
                        yield RoundtableEvent(
                            type="message",
                            agent=agent,
                            content=event.content,
                        )
                    elif event.type == "thinking":
                        yield RoundtableEvent(
                            type="thinking",
                            agent=agent,
                            content=event.content,
                        )
                    elif event.type == "done":
                        # Add complete message to session
                        full_content = "".join(content_parts)
                        total_tokens = (event.input_tokens or 0) + (event.output_tokens or 0)
                        msg = RoundtableMessage.create(
                            agent,
                            full_content,
                            tokens_used=total_tokens,
                            model=model,
                        )
                        session.add_message(msg)
                        span.set_attribute("roundtable.output_length", len(full_content))
                        span.set_attribute("roundtable.total_tokens", total_tokens)
                        span.set_status(Status(StatusCode.OK))
                        yield RoundtableEvent(
                            type="message",
                            agent=agent,
                            content="",  # Empty to signal completion
                            tokens=total_tokens,
                        )
                    elif event.type == "error":
                        span.set_attribute("roundtable.error", event.error or "Unknown error")
                        span.set_status(Status(StatusCode.ERROR, event.error or "Agent error"))
                        yield RoundtableEvent(
                            type="error",
                            agent=agent,
                            error=event.error,
                        )

            except Exception as e:
                logger.error(f"Agent {agent} error: {e}")
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                yield RoundtableEvent(
                    type="error",
                    agent=agent,
                    error=str(e),
                )

    async def deliberate(
        self,
        session: RoundtableSession,
        topic: str,
        max_rounds: int = 3,
    ) -> AsyncGenerator[RoundtableEvent]:
        """Run a deliberation where agents take turns.

        Args:
            session: The roundtable session.
            topic: The topic to deliberate on.
            max_rounds: Maximum rounds of back-and-forth.

        Yields:
            RoundtableEvents as agents deliberate.
        """
        # Initial message to both agents
        async for event in self.route_message(session, topic, "both"):
            yield event

        # Deliberation rounds
        for round_num in range(1, max_rounds):
            context = session.get_context()

            # Claude responds to what Gemini said
            prompt = f"Round {round_num + 1}: Please respond to the other agent's points."
            async for event in self._call_agent("claude", prompt, context, session):
                yield event

            context = session.get_context()

            # Gemini responds to Claude
            async for event in self._call_agent("gemini", prompt, context, session):
                yield event

        # Final consensus request
        consensus_prompt = """Based on our discussion, please provide a brief consensus summary
of the key points we agree on and any remaining disagreements."""

        async for event in self.route_message(session, consensus_prompt, "both"):
            yield event

    def end_session(self, session: RoundtableSession) -> dict[str, Any]:
        """End a session and return summary.

        Args:
            session: The session to end.

        Returns:
            Session summary with statistics.
        """
        summary = {
            "session_id": session.id,
            "project_id": session.project_id,
            "mode": session.mode,
            "message_count": len(session.messages),
            "total_tokens": session.total_tokens,
            "duration_seconds": (datetime.now() - session.created_at).total_seconds(),
        }

        # Clean up
        if session.id in self._sessions:
            del self._sessions[session.id]

        logger.info(f"Ended roundtable session {session.id}: {summary}")
        return summary


# Module-level singleton
_roundtable_service: RoundtableService | None = None


def get_roundtable_service() -> RoundtableService:
    """Get or create the roundtable service singleton."""
    global _roundtable_service
    if _roundtable_service is None:
        _roundtable_service = RoundtableService()
    return _roundtable_service
