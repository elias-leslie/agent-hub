"""Session management for Agent Hub client."""

from collections.abc import AsyncIterator
from typing import Any, TYPE_CHECKING

from agent_hub.models import (
    CompletionResponse,
    Message,
    SessionResponse,
    StreamChunk,
)

if TYPE_CHECKING:
    from agent_hub.client import AsyncAgentHubClient


class Session:
    """Manages a conversation session with automatic ID tracking.

    Example:
        async with AsyncAgentHubClient() as client:
            session = await client.session(
                project_id="my-project",
                provider="claude",
                model="claude-sonnet-4-5"
            )

            # Messages automatically persist in this session
            response = await session.complete("Hello!")
            print(response.content)

            # Continue the conversation
            response = await session.complete("Tell me more")
            print(response.content)

            # Get history
            history = await session.get_history()
            for msg in history:
                print(f"{msg.role}: {msg.content}")
    """

    def __init__(
        self,
        client: "AsyncAgentHubClient",
        session_id: str,
        project_id: str,
        provider: str,
        model: str,
    ) -> None:
        """Initialize session wrapper.

        Args:
            client: The async client to use for requests.
            session_id: The session ID.
            project_id: The project ID.
            provider: Provider name.
            model: Model identifier.
        """
        self._client = client
        self.session_id = session_id
        self.project_id = project_id
        self.provider = provider
        self.model = model
        self._local_messages: list[dict[str, str]] = []

    async def complete(
        self,
        content: str,
        *,
        max_tokens: int = 8192,
        temperature: float = 1.0,
    ) -> CompletionResponse:
        """Send a message and get a completion in this session.

        Args:
            content: The user message content.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            CompletionResponse with generated content.
        """
        # Track locally for convenience
        self._local_messages.append({"role": "user", "content": content})

        response = await self._client.complete(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=max_tokens,
            temperature=temperature,
            session_id=self.session_id,
            project_id=self.project_id,
        )

        # Track assistant response locally
        self._local_messages.append({"role": "assistant", "content": response.content})

        return response

    async def stream(
        self,
        content: str,
        *,
        max_tokens: int = 8192,
        temperature: float = 1.0,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion in this session.

        Args:
            content: The user message content.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Yields:
            StreamChunk for each streaming event.
        """
        # Track user message locally
        self._local_messages.append({"role": "user", "content": content})

        accumulated_content = ""
        async for chunk in self._client.stream(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=max_tokens,
            temperature=temperature,
            session_id=self.session_id,
        ):
            if chunk.type == "content":
                accumulated_content += chunk.content
            yield chunk

        # Track assistant response locally after stream completes
        if accumulated_content:
            self._local_messages.append(
                {"role": "assistant", "content": accumulated_content}
            )

    async def add_message(self, role: str, content: str) -> None:
        """Add a message to local context (for building multi-turn).

        Note: This adds to local tracking only. Use complete() or stream()
        to persist messages to the server.

        Args:
            role: Message role ("user", "assistant", or "system").
            content: Message content.
        """
        self._local_messages.append({"role": role, "content": content})

    async def get_history(self) -> list[Message]:
        """Get the full message history from the server.

        Returns:
            List of Message objects from the session.
        """
        session_data = await self._client.get_session(self.session_id)
        return session_data.messages

    async def get_local_history(self) -> list[dict[str, str]]:
        """Get locally tracked messages (not from server).

        Returns:
            List of message dicts tracked locally in this session.
        """
        return self._local_messages.copy()

    async def refresh(self) -> SessionResponse:
        """Refresh session data from server.

        Returns:
            Updated SessionResponse with current state.
        """
        return await self._client.get_session(self.session_id)

    async def close(self) -> None:
        """Mark the session as completed on the server."""
        await self._client.delete_session(self.session_id)


class SessionContext:
    """Async context manager for Session.

    Usage:
        async with client.session(...) as session:
            await session.complete("Hello")
    """

    def __init__(
        self,
        client: "AsyncAgentHubClient",
        project_id: str,
        provider: str,
        model: str,
        session_id: str | None = None,
    ) -> None:
        """Initialize session context.

        Args:
            client: The async client.
            project_id: Project identifier.
            provider: Provider name.
            model: Model identifier.
            session_id: Optional existing session ID to resume.
        """
        self._client = client
        self._project_id = project_id
        self._provider = provider
        self._model = model
        self._session_id = session_id
        self._session: Session | None = None

    async def __aenter__(self) -> Session:
        """Create or resume session on context entry."""
        if self._session_id:
            # Resume existing session
            session_data = await self._client.get_session(self._session_id)
            self._session = Session(
                client=self._client,
                session_id=session_data.id,
                project_id=session_data.project_id,
                provider=session_data.provider,
                model=session_data.model,
            )
        else:
            # Create new session
            session_data = await self._client.create_session(
                project_id=self._project_id,
                provider=self._provider,
                model=self._model,
            )
            self._session = Session(
                client=self._client,
                session_id=session_data.id,
                project_id=session_data.project_id,
                provider=session_data.provider,
                model=session_data.model,
            )
        return self._session

    async def __aexit__(self, *args: Any) -> None:
        """No-op on exit (session stays active for resume)."""
        # Don't close session - it can be resumed later
        pass
