"""Sync and async clients for Agent Hub API."""

from collections.abc import AsyncIterator
from typing import Any

import httpx

from agent_hub.exceptions import (
    AgentHubError,
    AuthenticationError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from agent_hub.models import (
    CompletionResponse,
    MessageInput,
    SessionCreate,
    SessionListResponse,
    SessionResponse,
    StreamChunk,
)


def _handle_error(response: httpx.Response) -> None:
    """Raise appropriate exception for error responses."""
    status = response.status_code
    try:
        detail = response.json().get("detail", response.text)
    except Exception:
        detail = response.text

    if status == 401:
        raise AuthenticationError(f"Authentication failed: {detail}", status_code=401)
    elif status == 429:
        retry_after = response.headers.get("Retry-After")
        raise RateLimitError(
            f"Rate limit exceeded: {detail}",
            retry_after=float(retry_after) if retry_after else None,
        )
    elif status == 422:
        raise ValidationError(f"Validation error: {detail}", status_code=422)
    elif status >= 500:
        raise ServerError(f"Server error: {detail}", status_code=status)
    else:
        raise AgentHubError(f"Request failed: {detail}", status_code=status)


class AgentHubClient:
    """Synchronous client for Agent Hub API.

    Example:
        client = AgentHubClient(base_url="http://localhost:8003")
        response = client.complete(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "Hello!"}]
        )
        print(response.content)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8003",
        api_key: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        """Initialize the client.

        Args:
            base_url: Agent Hub API base URL.
            api_key: Optional API key for authentication.
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Get or create httpx client."""
        if self._client is None:
            headers: dict[str, str] = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self) -> "AgentHubClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def complete(
        self,
        model: str,
        messages: list[dict[str, str] | MessageInput],
        *,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        session_id: str | None = None,
        project_id: str = "default",
        enable_caching: bool = True,
        persist_session: bool = True,
    ) -> CompletionResponse:
        """Generate a completion.

        Args:
            model: Model identifier (e.g., "claude-sonnet-4-5").
            messages: Conversation messages.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            session_id: Optional session ID to continue.
            project_id: Project ID for session tracking.
            enable_caching: Enable prompt caching.
            persist_session: Persist messages to database.

        Returns:
            CompletionResponse with generated content.

        Raises:
            AuthenticationError: If authentication fails.
            RateLimitError: If rate limit is exceeded.
            ValidationError: If request validation fails.
            ServerError: If server returns 5xx error.
            AgentHubError: For other errors.
        """
        client = self._get_client()

        # Normalize messages to dicts
        msg_dicts = []
        for msg in messages:
            if isinstance(msg, MessageInput):
                msg_dicts.append(msg.model_dump())
            else:
                msg_dicts.append(msg)

        payload = {
            "model": model,
            "messages": msg_dicts,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "project_id": project_id,
            "enable_caching": enable_caching,
            "persist_session": persist_session,
        }
        if session_id:
            payload["session_id"] = session_id

        response = client.post("/api/complete", json=payload)

        if not response.is_success:
            _handle_error(response)

        return CompletionResponse.model_validate(response.json())

    def create_session(
        self,
        project_id: str,
        provider: str,
        model: str,
    ) -> SessionResponse:
        """Create a new conversation session.

        Args:
            project_id: Project identifier.
            provider: Provider name ("claude" or "gemini").
            model: Model identifier.

        Returns:
            SessionResponse with session details.
        """
        client = self._get_client()

        payload = SessionCreate(
            project_id=project_id,
            provider=provider,
            model=model,
        )

        response = client.post("/api/sessions", json=payload.model_dump())

        if not response.is_success:
            _handle_error(response)

        return SessionResponse.model_validate(response.json())

    def get_session(self, session_id: str) -> SessionResponse:
        """Get a session by ID with all messages.

        Args:
            session_id: Session identifier.

        Returns:
            SessionResponse with session details and messages.
        """
        client = self._get_client()

        response = client.get(f"/api/sessions/{session_id}")

        if not response.is_success:
            _handle_error(response)

        return SessionResponse.model_validate(response.json())

    def list_sessions(
        self,
        project_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> SessionListResponse:
        """List sessions with pagination.

        Args:
            project_id: Filter by project.
            status: Filter by status.
            page: Page number.
            page_size: Items per page.

        Returns:
            SessionListResponse with sessions and pagination info.
        """
        client = self._get_client()

        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if project_id:
            params["project_id"] = project_id
        if status:
            params["status"] = status

        response = client.get("/api/sessions", params=params)

        if not response.is_success:
            _handle_error(response)

        return SessionListResponse.model_validate(response.json())

    def delete_session(self, session_id: str) -> None:
        """Delete/archive a session.

        Args:
            session_id: Session identifier.
        """
        client = self._get_client()

        response = client.delete(f"/api/sessions/{session_id}")

        if not response.is_success:
            _handle_error(response)


class AsyncAgentHubClient:
    """Asynchronous client for Agent Hub API.

    Example:
        async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
            response = await client.complete(
                model="claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Hello!"}]
            )
            print(response.content)

            # Streaming
            async for chunk in client.stream(
                model="claude-sonnet-4-5",
                messages=[{"role": "user", "content": "Tell me a story"}]
            ):
                print(chunk.content, end="", flush=True)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8003",
        api_key: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        """Initialize the client.

        Args:
            base_url: Agent Hub API base URL.
            api_key: Optional API key for authentication.
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async httpx client."""
        if self._client is None:
            headers: dict[str, str] = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "AsyncAgentHubClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def complete(
        self,
        model: str,
        messages: list[dict[str, str] | MessageInput],
        *,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        session_id: str | None = None,
        project_id: str = "default",
        enable_caching: bool = True,
        persist_session: bool = True,
    ) -> CompletionResponse:
        """Generate a completion asynchronously.

        Args:
            model: Model identifier (e.g., "claude-sonnet-4-5").
            messages: Conversation messages.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            session_id: Optional session ID to continue.
            project_id: Project ID for session tracking.
            enable_caching: Enable prompt caching.
            persist_session: Persist messages to database.

        Returns:
            CompletionResponse with generated content.

        Raises:
            AuthenticationError: If authentication fails.
            RateLimitError: If rate limit is exceeded.
            ValidationError: If request validation fails.
            ServerError: If server returns 5xx error.
            AgentHubError: For other errors.
        """
        client = await self._get_client()

        # Normalize messages to dicts
        msg_dicts = []
        for msg in messages:
            if isinstance(msg, MessageInput):
                msg_dicts.append(msg.model_dump())
            else:
                msg_dicts.append(msg)

        payload = {
            "model": model,
            "messages": msg_dicts,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "project_id": project_id,
            "enable_caching": enable_caching,
            "persist_session": persist_session,
        }
        if session_id:
            payload["session_id"] = session_id

        response = await client.post("/api/complete", json=payload)

        if not response.is_success:
            _handle_error(response)

        return CompletionResponse.model_validate(response.json())

    async def stream(
        self,
        model: str,
        messages: list[dict[str, str] | MessageInput],
        *,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        session_id: str | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion using WebSocket with automatic reconnection.

        Args:
            model: Model identifier.
            messages: Conversation messages.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            session_id: Optional session ID.
            max_retries: Maximum reconnection attempts on disconnect.
            retry_delay: Delay between reconnection attempts in seconds.

        Yields:
            StreamChunk for each streaming event.

        Raises:
            AgentHubError: If connection or streaming fails after retries.
        """
        import asyncio
        import json

        # Normalize messages to dicts
        msg_dicts = []
        for msg in messages:
            if isinstance(msg, MessageInput):
                msg_dicts.append(msg.model_dump())
            else:
                msg_dicts.append(msg)

        # Build WebSocket URL
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/api/stream"

        try:
            import websockets
        except ImportError:
            raise ImportError(
                "websockets package required for streaming. "
                "Install with: pip install websockets"
            )

        request = {
            "type": "request",
            "model": model,
            "messages": msg_dicts,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if session_id:
            request["session_id"] = session_id

        retries = 0
        while retries <= max_retries:
            try:
                async with websockets.connect(ws_url) as websocket:
                    await websocket.send(json.dumps(request))

                    async for raw_message in websocket:
                        data = json.loads(raw_message)
                        chunk = StreamChunk.model_validate(data)
                        yield chunk

                        if chunk.type in ("done", "cancelled", "error"):
                            return  # Normal completion

                    return  # Connection closed gracefully

            except websockets.exceptions.ConnectionClosed as e:
                retries += 1
                if retries > max_retries:
                    raise AgentHubError(
                        f"WebSocket connection closed after {max_retries} retries: {e}"
                    ) from e
                await asyncio.sleep(retry_delay * retries)

            except Exception as e:
                raise AgentHubError(f"Streaming error: {e}") from e

    async def stream_sse(
        self,
        model: str,
        messages: list[dict[str, str] | MessageInput],
        *,
        max_tokens: int = 4096,
        temperature: float = 1.0,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion using SSE (Server-Sent Events) via OpenAI-compatible API.

        This is an alternative to WebSocket streaming that uses the
        OpenAI-compatible /v1/chat/completions endpoint with stream=true.

        Args:
            model: Model identifier.
            messages: Conversation messages.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Yields:
            StreamChunk for each streaming event.

        Raises:
            AgentHubError: If connection or streaming fails.
        """
        import json

        client = await self._get_client()

        # Normalize messages
        msg_dicts = []
        for msg in messages:
            if isinstance(msg, MessageInput):
                msg_dicts.append(msg.model_dump())
            else:
                msg_dicts.append(msg)

        payload = {
            "model": model,
            "messages": msg_dicts,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        try:
            async with client.stream("POST", "/api/v1/chat/completions", json=payload) as response:
                if not response.is_success:
                    await response.aread()
                    _handle_error(response)

                buffer = ""
                async for line in response.aiter_lines():
                    if not line:
                        continue

                    if line.startswith("data: "):
                        data_str = line[6:]

                        if data_str == "[DONE]":
                            yield StreamChunk(type="done", finish_reason="stop")
                            return

                        try:
                            data = json.loads(data_str)
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                finish_reason = choices[0].get("finish_reason")

                                if content:
                                    yield StreamChunk(type="content", content=content)

                                if finish_reason:
                                    yield StreamChunk(
                                        type="done",
                                        finish_reason=finish_reason,
                                    )
                                    return
                        except json.JSONDecodeError:
                            continue

        except Exception as e:
            raise AgentHubError(f"SSE streaming error: {e}") from e

    async def cancel_stream(self, session_id: str) -> dict[str, Any]:
        """Cancel an active streaming session.

        Args:
            session_id: Session identifier with active stream.

        Returns:
            Dict with cancellation status and token counts.
        """
        client = await self._get_client()

        response = await client.post(f"/api/sessions/{session_id}/cancel")

        if not response.is_success:
            _handle_error(response)

        return response.json()

    async def create_session(
        self,
        project_id: str,
        provider: str,
        model: str,
    ) -> SessionResponse:
        """Create a new conversation session.

        Args:
            project_id: Project identifier.
            provider: Provider name ("claude" or "gemini").
            model: Model identifier.

        Returns:
            SessionResponse with session details.
        """
        client = await self._get_client()

        payload = SessionCreate(
            project_id=project_id,
            provider=provider,
            model=model,
        )

        response = await client.post("/api/sessions", json=payload.model_dump())

        if not response.is_success:
            _handle_error(response)

        return SessionResponse.model_validate(response.json())

    async def get_session(self, session_id: str) -> SessionResponse:
        """Get a session by ID with all messages.

        Args:
            session_id: Session identifier.

        Returns:
            SessionResponse with session details and messages.
        """
        client = await self._get_client()

        response = await client.get(f"/api/sessions/{session_id}")

        if not response.is_success:
            _handle_error(response)

        return SessionResponse.model_validate(response.json())

    async def list_sessions(
        self,
        project_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> SessionListResponse:
        """List sessions with pagination.

        Args:
            project_id: Filter by project.
            status: Filter by status.
            page: Page number.
            page_size: Items per page.

        Returns:
            SessionListResponse with sessions and pagination info.
        """
        client = await self._get_client()

        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if project_id:
            params["project_id"] = project_id
        if status:
            params["status"] = status

        response = await client.get("/api/sessions", params=params)

        if not response.is_success:
            _handle_error(response)

        return SessionListResponse.model_validate(response.json())

    async def delete_session(self, session_id: str) -> None:
        """Delete/archive a session.

        Args:
            session_id: Session identifier.
        """
        client = await self._get_client()

        response = await client.delete(f"/api/sessions/{session_id}")

        if not response.is_success:
            _handle_error(response)
