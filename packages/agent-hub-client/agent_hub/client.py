"""Sync and async clients for Agent Hub API."""

import inspect
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

from agent_hub.exceptions import (
    AgentHubError,
    AuthenticationError,
    ClientDisabledError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from agent_hub.models import (
    CompletionResponse,
    MessageInput,
    RoutingConfig,
    SessionCreate,
    SessionListResponse,
    SessionResponse,
    StreamChunk,
    ToolDefinition,
    ToolResultMessage,
)


def _get_caller_path(skip_frames: int = 2) -> str | None:
    """Get the file path of the caller using inspect.

    Args:
        skip_frames: Number of frames to skip (to get past library internals).

    Returns:
        Relative path from cwd to caller file, or absolute path if outside cwd.
    """
    try:
        stack = inspect.stack()
        # Skip frames: _get_caller_path, _get_client, caller's method
        if len(stack) > skip_frames:
            frame = stack[skip_frames]
            caller_file = Path(frame.filename)
            try:
                # Try to make it relative to cwd for cleaner logs
                return str(caller_file.relative_to(Path.cwd()))
            except ValueError:
                # Outside cwd, use absolute path
                return str(caller_file)
    except Exception:
        pass
    return None


def _handle_error(response: httpx.Response) -> None:
    """Raise appropriate exception for error responses."""
    status = response.status_code
    try:
        data = response.json()
        detail = data.get("detail", response.text)
    except Exception:
        detail = response.text
        data = {}

    if status == 401:
        raise AuthenticationError(f"Authentication failed: {detail}", status_code=401)
    elif status == 403:
        # Check for kill switch (client disabled) response
        error_type = data.get("error") if isinstance(data, dict) else None
        if error_type in ("client_disabled", "client_purpose_disabled", "purpose_disabled"):
            retry_after = data.get("retry_after", -1) if isinstance(data, dict) else -1
            if retry_after == -1:
                raise ClientDisabledError(
                    message=data.get("message", "Client disabled") if isinstance(data, dict) else "Client disabled",
                    blocked_entity=data.get("blocked_entity") if isinstance(data, dict) else None,
                    reason=data.get("reason") if isinstance(data, dict) else None,
                    disabled_at=data.get("disabled_at") if isinstance(data, dict) else None,
                )
        raise AgentHubError(f"Forbidden: {detail}", status_code=403)
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
        client = AgentHubClient(
            base_url="http://localhost:8003",
            client_name="my-app"
        )
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
        client_name: str | None = None,
        auto_inject_headers: bool = True,
    ) -> None:
        """Initialize the client.

        Args:
            base_url: Agent Hub API base URL.
            api_key: Optional API key for authentication.
            timeout: Request timeout in seconds.
            client_name: Name of this client for usage tracking (required by API).
                If not provided, auto-detected from caller module.
            auto_inject_headers: Whether to auto-inject X-Source-Client and
                X-Source-Path headers. Set to False to disable.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.auto_inject_headers = auto_inject_headers

        # Auto-detect client name from caller if not provided
        if client_name:
            self.client_name = client_name
        else:
            # Use caller's module name as client name
            caller_path = _get_caller_path(skip_frames=2)
            if caller_path:
                self.client_name = Path(caller_path).stem
            else:
                self.client_name = "unknown-client"

        self._client: httpx.Client | None = None

        # Dormant mode: set when client receives kill switch (403 with retry_after=-1)
        self._disabled = False
        self._disabled_reason: str | None = None

    def is_disabled(self) -> bool:
        """Check if client is in dormant mode due to kill switch."""
        return self._disabled

    def re_enable(self) -> None:
        """Re-enable client after it was disabled by kill switch.

        Call this to attempt requests again after the admin has re-enabled
        the client in Agent Hub.
        """
        self._disabled = False
        self._disabled_reason = None

    def _check_disabled(self) -> None:
        """Check if client is disabled and raise if so."""
        if self._disabled:
            raise ClientDisabledError(
                message=f"Client is disabled: {self._disabled_reason or 'kill switch activated'}",
                blocked_entity=self.client_name,
                reason=self._disabled_reason,
            )

    def _get_client(self) -> httpx.Client:
        """Get or create httpx client."""
        if self._client is None:
            headers: dict[str, str] = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            # Auto-inject source headers for usage control
            if self.auto_inject_headers:
                headers["X-Source-Client"] = self.client_name

            self._client = httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    def _inject_source_path(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        """Inject X-Source-Path header with caller location."""
        headers = extra_headers.copy() if extra_headers else {}
        if self.auto_inject_headers:
            caller_path = _get_caller_path(skip_frames=3)
            if caller_path:
                headers["X-Source-Path"] = caller_path
        return headers

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
        messages: list[dict[str, str] | MessageInput | ToolResultMessage],
        *,
        project_id: str,
        max_tokens: int = 8192,
        temperature: float = 1.0,
        session_id: str | None = None,
        purpose: str | None = None,
        external_id: str | None = None,
        enable_caching: bool = True,
        routing_config: RoutingConfig | dict[str, Any] | None = None,
        tools: list[dict[str, Any] | ToolDefinition] | None = None,
        enable_programmatic_tools: bool = False,
        container_id: str | None = None,
    ) -> CompletionResponse:
        """Generate a completion.

        Args:
            model: Model identifier (e.g., "claude-sonnet-4-5").
            messages: Conversation messages (includes ToolResultMessage for tool results).
            project_id: Project ID for session tracking (required).
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            session_id: Optional session ID to continue.
            purpose: Purpose of this session (task_enrichment, code_generation, etc.).
            external_id: External ID for task linkage (e.g., task-123).
            enable_caching: Enable prompt caching.
            routing_config: Capability-based routing config. If provided with capability,
                overrides model selection. If is_autonomous=True, injects safety directive.
            tools: Tool definitions for model to call.
            enable_programmatic_tools: Enable code execution to call tools (Claude only).
            container_id: Container ID for code execution continuity (Claude only).

        Returns:
            CompletionResponse with generated content and optional tool_calls.

        Raises:
            AuthenticationError: If authentication fails.
            RateLimitError: If rate limit is exceeded.
            ValidationError: If request validation fails.
            ServerError: If server returns 5xx error.
            ClientDisabledError: If client is disabled via kill switch.
            AgentHubError: For other errors.
        """
        # Check if client is disabled (dormant mode)
        self._check_disabled()

        client = self._get_client()

        # Normalize messages to dicts
        msg_dicts = []
        for msg in messages:
            if isinstance(msg, (MessageInput, ToolResultMessage)):
                msg_dicts.append(msg.model_dump())
            else:
                msg_dicts.append(msg)

        # Normalize tools to dicts
        tool_dicts = None
        if tools:
            tool_dicts = []
            for tool in tools:
                if isinstance(tool, ToolDefinition):
                    tool_dicts.append(tool.model_dump())
                else:
                    tool_dicts.append(tool)

        payload: dict[str, Any] = {
            "model": model,
            "messages": msg_dicts,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "project_id": project_id,
            "enable_caching": enable_caching,
        }
        if session_id:
            payload["session_id"] = session_id
        if purpose:
            payload["purpose"] = purpose
        if external_id:
            payload["external_id"] = external_id
        if routing_config:
            if isinstance(routing_config, RoutingConfig):
                payload["routing_config"] = routing_config.model_dump(exclude_none=True)
            else:
                payload["routing_config"] = routing_config
        if tool_dicts:
            payload["tools"] = tool_dicts
        if enable_programmatic_tools:
            payload["enable_programmatic_tools"] = True
        if container_id:
            payload["container_id"] = container_id

        headers = self._inject_source_path()
        response = client.post("/api/complete", json=payload, headers=headers)

        if not response.is_success:
            try:
                _handle_error(response)
            except ClientDisabledError as e:
                # Enter dormant mode
                self._disabled = True
                self._disabled_reason = e.reason
                raise

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

        headers = self._inject_source_path()
        response = client.post("/api/sessions", json=payload.model_dump(), headers=headers)

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

        headers = self._inject_source_path()
        response = client.get(f"/api/sessions/{session_id}", headers=headers)

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

        headers = self._inject_source_path()
        response = client.get("/api/sessions", params=params, headers=headers)

        if not response.is_success:
            _handle_error(response)

        return SessionListResponse.model_validate(response.json())

    def delete_session(self, session_id: str) -> None:
        """Delete/archive a session.

        Args:
            session_id: Session identifier.
        """
        client = self._get_client()

        headers = self._inject_source_path()
        response = client.delete(f"/api/sessions/{session_id}", headers=headers)

        if not response.is_success:
            _handle_error(response)

    def close_session(self, session_id: str) -> dict[str, Any]:
        """Explicitly close a session.

        Marks the session as completed. Use for clean session termination.
        This is idempotent - calling on an already-completed session is safe.

        Args:
            session_id: Session identifier.

        Returns:
            Dict with id, status, and message.
        """
        client = self._get_client()

        headers = self._inject_source_path()
        response = client.post(f"/api/sessions/{session_id}/close", headers=headers)

        if not response.is_success:
            _handle_error(response)

        return response.json()

    def generate_image(
        self,
        prompt: str,
        *,
        project_id: str,
        purpose: str | None = None,
        model: str = "gemini-3-pro-image-preview",
        size: str = "1024x1024",
        style: str | None = None,
    ) -> "ImageGenerationResponse":
        """Generate an image from a text prompt.

        Args:
            prompt: Text description of desired image.
            project_id: Project ID for session tracking (required).
            purpose: Purpose of this generation (e.g., mockup_generation).
            model: Model identifier for image generation.
            size: Image dimensions (e.g., "1024x1024").
            style: Style hint (e.g., "photorealistic", "artistic").

        Returns:
            ImageGenerationResponse with base64 image data.

        Raises:
            AuthenticationError: If authentication fails.
            RateLimitError: If rate limit is exceeded.
            ValidationError: If request validation fails.
            ServerError: If server returns 5xx error.
            AgentHubError: For other errors.
        """
        from agent_hub.models import ImageGenerationResponse

        client = self._get_client()

        payload: dict[str, Any] = {
            "prompt": prompt,
            "project_id": project_id,
            "model": model,
            "size": size,
        }
        if purpose:
            payload["purpose"] = purpose
        if style:
            payload["style"] = style

        headers = self._inject_source_path()
        response = client.post("/api/generate-image", json=payload, headers=headers)

        if not response.is_success:
            _handle_error(response)

        return ImageGenerationResponse.model_validate(response.json())

    def run_agent(
        self,
        task: str,
        *,
        provider: str = "claude",
        model: str | None = None,
        system_prompt: str | None = None,
        max_tokens: int = 64000,
        temperature: float = 1.0,
        max_turns: int = 20,
        budget_tokens: int | None = None,
        enable_code_execution: bool = True,
        container_id: str | None = None,
        working_dir: str | None = None,
        timeout_seconds: float = 300.0,
    ) -> "AgentRunResponse":
        """Run an agent on a task with tool execution.

        For Claude: Uses code_execution sandbox for autonomous tool calling.
        For Gemini: Runs without tools (completion only).

        The agent will execute in a loop, calling tools as needed until the task
        is complete or max_turns is reached.

        Args:
            task: Task description for the agent.
            provider: LLM provider ("claude" or "gemini").
            model: Model override.
            system_prompt: Custom system prompt.
            max_tokens: Max tokens per turn.
            temperature: Sampling temperature.
            max_turns: Maximum agentic turns.
            budget_tokens: Extended thinking budget (Claude only).
            enable_code_execution: Enable code execution sandbox (Claude only).
            container_id: Reuse existing container (Claude only).
            working_dir: Working directory for agent execution.
            timeout_seconds: Request timeout.

        Returns:
            AgentRunResponse with execution results and progress log.

        Raises:
            AuthenticationError: If authentication fails.
            RateLimitError: If rate limit is exceeded.
            ValidationError: If request validation fails.
            ServerError: If server returns 5xx error.
            AgentHubError: For other errors.
        """
        from agent_hub.models import AgentRunResponse

        client = self._get_client()

        payload: dict[str, Any] = {
            "task": task,
            "provider": provider,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "max_turns": max_turns,
            "enable_code_execution": enable_code_execution,
            "timeout_seconds": timeout_seconds,
        }
        if model:
            payload["model"] = model
        if system_prompt:
            payload["system_prompt"] = system_prompt
        if budget_tokens:
            payload["budget_tokens"] = budget_tokens
        if container_id:
            payload["container_id"] = container_id
        if working_dir:
            payload["working_dir"] = working_dir

        headers = self._inject_source_path()
        response = client.post(
            "/api/orchestration/run-agent",
            json=payload,
            headers=headers,
            timeout=timeout_seconds + 30,  # Allow extra time for network
        )

        if not response.is_success:
            _handle_error(response)

        return AgentRunResponse.model_validate(response.json())


class AsyncAgentHubClient:
    """Asynchronous client for Agent Hub API.

    Example:
        async with AsyncAgentHubClient(
            base_url="http://localhost:8003",
            client_name="my-app"
        ) as client:
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
        client_name: str | None = None,
        auto_inject_headers: bool = True,
    ) -> None:
        """Initialize the client.

        Args:
            base_url: Agent Hub API base URL.
            api_key: Optional API key for authentication.
            timeout: Request timeout in seconds.
            client_name: Name of this client for usage tracking (required by API).
                If not provided, auto-detected from caller module.
            auto_inject_headers: Whether to auto-inject X-Source-Client and
                X-Source-Path headers. Set to False to disable.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.auto_inject_headers = auto_inject_headers

        # Auto-detect client name from caller if not provided
        if client_name:
            self.client_name = client_name
        else:
            # Use caller's module name as client name
            caller_path = _get_caller_path(skip_frames=2)
            if caller_path:
                self.client_name = Path(caller_path).stem
            else:
                self.client_name = "unknown-client"

        self._client: httpx.AsyncClient | None = None

        # Dormant mode: set when client receives kill switch (403 with retry_after=-1)
        self._disabled = False
        self._disabled_reason: str | None = None

    def is_disabled(self) -> bool:
        """Check if client is in dormant mode due to kill switch."""
        return self._disabled

    def re_enable(self) -> None:
        """Re-enable client after it was disabled by kill switch.

        Call this to attempt requests again after the admin has re-enabled
        the client in Agent Hub.
        """
        self._disabled = False
        self._disabled_reason = None

    def _check_disabled(self) -> None:
        """Check if client is disabled and raise if so."""
        if self._disabled:
            raise ClientDisabledError(
                message=f"Client is disabled: {self._disabled_reason or 'kill switch activated'}",
                blocked_entity=self.client_name,
                reason=self._disabled_reason,
            )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async httpx client."""
        if self._client is None:
            headers: dict[str, str] = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            # Auto-inject source headers for usage control
            if self.auto_inject_headers:
                headers["X-Source-Client"] = self.client_name

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    def _inject_source_path(self, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
        """Inject X-Source-Path header with caller location."""
        headers = extra_headers.copy() if extra_headers else {}
        if self.auto_inject_headers:
            caller_path = _get_caller_path(skip_frames=3)
            if caller_path:
                headers["X-Source-Path"] = caller_path
        return headers

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
        messages: list[dict[str, str] | MessageInput | ToolResultMessage],
        *,
        project_id: str,
        max_tokens: int = 8192,
        temperature: float = 1.0,
        session_id: str | None = None,
        purpose: str | None = None,
        enable_caching: bool = True,
        routing_config: RoutingConfig | dict[str, Any] | None = None,
        tools: list[dict[str, Any] | ToolDefinition] | None = None,
        enable_programmatic_tools: bool = False,
        container_id: str | None = None,
    ) -> CompletionResponse:
        """Generate a completion asynchronously.

        Args:
            model: Model identifier (e.g., "claude-sonnet-4-5").
            messages: Conversation messages (includes ToolResultMessage for tool results).
            project_id: Project ID for session tracking (required).
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            session_id: Optional session ID to continue.
            purpose: Purpose of this session (task_enrichment, code_generation, etc.).
            enable_caching: Enable prompt caching.
            routing_config: Capability-based routing config. If provided with capability,
                overrides model selection. If is_autonomous=True, injects safety directive.
            tools: Tool definitions for model to call.
            enable_programmatic_tools: Enable code execution to call tools (Claude only).
            container_id: Container ID for code execution continuity (Claude only).

        Returns:
            CompletionResponse with generated content and optional tool_calls.

        Raises:
            AuthenticationError: If authentication fails.
            RateLimitError: If rate limit is exceeded.
            ValidationError: If request validation fails.
            ServerError: If server returns 5xx error.
            ClientDisabledError: If client is disabled via kill switch.
            AgentHubError: For other errors.
        """
        # Check if client is disabled (dormant mode)
        self._check_disabled()

        client = await self._get_client()

        # Normalize messages to dicts
        msg_dicts = []
        for msg in messages:
            if isinstance(msg, (MessageInput, ToolResultMessage)):
                msg_dicts.append(msg.model_dump())
            else:
                msg_dicts.append(msg)

        # Normalize tools to dicts
        tool_dicts = None
        if tools:
            tool_dicts = []
            for tool in tools:
                if isinstance(tool, ToolDefinition):
                    tool_dicts.append(tool.model_dump())
                else:
                    tool_dicts.append(tool)

        payload: dict[str, Any] = {
            "model": model,
            "messages": msg_dicts,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "project_id": project_id,
            "enable_caching": enable_caching,
        }
        if session_id:
            payload["session_id"] = session_id
        if purpose:
            payload["purpose"] = purpose
        if routing_config:
            if isinstance(routing_config, RoutingConfig):
                payload["routing_config"] = routing_config.model_dump(exclude_none=True)
            else:
                payload["routing_config"] = routing_config
        if tool_dicts:
            payload["tools"] = tool_dicts
        if enable_programmatic_tools:
            payload["enable_programmatic_tools"] = True
        if container_id:
            payload["container_id"] = container_id

        headers = self._inject_source_path()
        response = await client.post("/api/complete", json=payload, headers=headers)

        if not response.is_success:
            try:
                _handle_error(response)
            except ClientDisabledError as e:
                # Enter dormant mode
                self._disabled = True
                self._disabled_reason = e.reason
                raise

        return CompletionResponse.model_validate(response.json())

    async def stream(
        self,
        model: str,
        messages: list[dict[str, str] | MessageInput],
        *,
        max_tokens: int = 8192,
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
                "websockets package required for streaming. Install with: pip install websockets"
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
        max_tokens: int = 8192,
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

        headers = self._inject_source_path()
        try:
            async with client.stream("POST", "/api/v1/chat/completions", json=payload, headers=headers) as response:
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

        headers = self._inject_source_path()
        response = await client.post(f"/api/sessions/{session_id}/cancel", headers=headers)

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

        headers = self._inject_source_path()
        response = await client.post("/api/sessions", json=payload.model_dump(), headers=headers)

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

        headers = self._inject_source_path()
        response = await client.get(f"/api/sessions/{session_id}", headers=headers)

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

        headers = self._inject_source_path()
        response = await client.get("/api/sessions", params=params, headers=headers)

        if not response.is_success:
            _handle_error(response)

        return SessionListResponse.model_validate(response.json())

    async def delete_session(self, session_id: str) -> None:
        """Delete/archive a session.

        Args:
            session_id: Session identifier.
        """
        client = await self._get_client()

        headers = self._inject_source_path()
        response = await client.delete(f"/api/sessions/{session_id}", headers=headers)

        if not response.is_success:
            _handle_error(response)

    async def close_session(self, session_id: str) -> dict[str, Any]:
        """Explicitly close a session.

        Marks the session as completed. Use for clean session termination.
        This is idempotent - calling on an already-completed session is safe.

        Args:
            session_id: Session identifier.

        Returns:
            Dict with id, status, and message.
        """
        client = await self._get_client()

        headers = self._inject_source_path()
        response = await client.post(f"/api/sessions/{session_id}/close", headers=headers)

        if not response.is_success:
            _handle_error(response)

        return response.json()

    async def generate_image(
        self,
        prompt: str,
        *,
        project_id: str,
        purpose: str | None = None,
        model: str = "gemini-3-pro-image-preview",
        size: str = "1024x1024",
        style: str | None = None,
    ) -> "ImageGenerationResponse":
        """Generate an image from a text prompt asynchronously.

        Args:
            prompt: Text description of desired image.
            project_id: Project ID for session tracking (required).
            purpose: Purpose of this generation (e.g., mockup_generation).
            model: Model identifier for image generation.
            size: Image dimensions (e.g., "1024x1024").
            style: Style hint (e.g., "photorealistic", "artistic").

        Returns:
            ImageGenerationResponse with base64 image data.

        Raises:
            AuthenticationError: If authentication fails.
            RateLimitError: If rate limit is exceeded.
            ValidationError: If request validation fails.
            ServerError: If server returns 5xx error.
            AgentHubError: For other errors.
        """
        from agent_hub.models import ImageGenerationResponse

        client = await self._get_client()

        payload: dict[str, Any] = {
            "prompt": prompt,
            "project_id": project_id,
            "model": model,
            "size": size,
        }
        if purpose:
            payload["purpose"] = purpose
        if style:
            payload["style"] = style

        headers = self._inject_source_path()
        response = await client.post("/api/generate-image", json=payload, headers=headers)

        if not response.is_success:
            _handle_error(response)

        return ImageGenerationResponse.model_validate(response.json())

    async def run_agent(
        self,
        task: str,
        *,
        provider: str = "claude",
        model: str | None = None,
        system_prompt: str | None = None,
        max_tokens: int = 64000,
        temperature: float = 1.0,
        max_turns: int = 20,
        budget_tokens: int | None = None,
        enable_code_execution: bool = True,
        container_id: str | None = None,
        working_dir: str | None = None,
        timeout_seconds: float = 300.0,
    ) -> "AgentRunResponse":
        """Run an agent on a task with tool execution.

        For Claude: Uses code_execution sandbox for autonomous tool calling.
        For Gemini: Runs without tools (completion only).

        The agent will execute in a loop, calling tools as needed until the task
        is complete or max_turns is reached.

        Args:
            task: Task description for the agent.
            provider: LLM provider ("claude" or "gemini").
            model: Model override.
            system_prompt: Custom system prompt.
            max_tokens: Max tokens per turn.
            temperature: Sampling temperature.
            max_turns: Maximum agentic turns.
            budget_tokens: Extended thinking budget (Claude only).
            enable_code_execution: Enable code execution sandbox (Claude only).
            container_id: Reuse existing container (Claude only).
            working_dir: Working directory for agent execution.
            timeout_seconds: Request timeout.

        Returns:
            AgentRunResponse with execution results and progress log.

        Raises:
            AuthenticationError: If authentication fails.
            RateLimitError: If rate limit is exceeded.
            ValidationError: If request validation fails.
            ServerError: If server returns 5xx error.
            AgentHubError: For other errors.
        """
        from agent_hub.models import AgentRunResponse

        client = await self._get_client()

        payload: dict[str, Any] = {
            "task": task,
            "provider": provider,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "max_turns": max_turns,
            "enable_code_execution": enable_code_execution,
            "timeout_seconds": timeout_seconds,
        }
        if model:
            payload["model"] = model
        if system_prompt:
            payload["system_prompt"] = system_prompt
        if budget_tokens:
            payload["budget_tokens"] = budget_tokens
        if container_id:
            payload["container_id"] = container_id
        if working_dir:
            payload["working_dir"] = working_dir

        headers = self._inject_source_path()
        response = await client.post(
            "/api/orchestration/run-agent",
            json=payload,
            headers=headers,
            timeout=timeout_seconds + 30,  # Allow extra time for network
        )

        if not response.is_success:
            _handle_error(response)

        return AgentRunResponse.model_validate(response.json())

    def session(
        self,
        project_id: str,
        provider: str,
        model: str,
        session_id: str | None = None,
    ) -> "SessionContext":
        """Create a session context manager.

        Use this to manage a conversation session with automatic ID tracking.
        Messages sent through the session are persisted to the server.

        Args:
            project_id: Project identifier.
            provider: Provider name ("claude" or "gemini").
            model: Model identifier.
            session_id: Optional existing session ID to resume.

        Returns:
            SessionContext that can be used as async context manager.

        Example:
            async with client.session(
                project_id="my-project",
                provider="claude",
                model="claude-sonnet-4-5"
            ) as session:
                response = await session.complete("Hello!")
                print(response.content)

                # Continue conversation in same session
                response = await session.complete("Tell me more")

            # Resume existing session
            async with client.session(
                project_id="my-project",
                provider="claude",
                model="claude-sonnet-4-5",
                session_id="existing-session-id"
            ) as session:
                history = await session.get_history()
        """
        from agent_hub.session import SessionContext

        return SessionContext(
            client=self,
            project_id=project_id,
            provider=provider,
            model=model,
            session_id=session_id,
        )
