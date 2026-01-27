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
        client_id: str | None = None,
        client_secret: str | None = None,
        request_source: str | None = None,
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
            client_id: Client ID for access control authentication.
            client_secret: Client secret for access control authentication.
            request_source: Request source identifier for tracking.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.auto_inject_headers = auto_inject_headers
        self.client_id = client_id
        self.client_secret = client_secret
        self.request_source = request_source

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

            # Inject access control headers if credentials provided
            if self.client_id:
                headers["X-Client-Id"] = self.client_id
            if self.client_secret:
                headers["X-Client-Secret"] = self.client_secret
            if self.request_source:
                headers["X-Request-Source"] = self.request_source

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
        messages: list[dict[str, str] | MessageInput | ToolResultMessage],
        *,
        project_id: str,
        agent_slug: str | None = None,
        model: str | None = None,
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
            messages: Conversation messages (includes ToolResultMessage for tool results).
            project_id: Project ID for session tracking (required).
            agent_slug: Agent slug for routing (e.g., "coder", "planner"). When provided,
                loads agent config, injects mandates, and uses fallback chains. PREFERRED.
            model: DEPRECATED - Use agent_slug instead. Direct model specification.
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
            ValueError: If neither agent_slug nor model is provided.
            AgentHubError: For other errors.
            ValueError: If neither agent_slug nor model is provided.
        """
        # Validate: require agent_slug (preferred) or model (deprecated)
        if not agent_slug and not model:
            raise ValueError(
                "Either 'agent_slug' or 'model' must be provided. "
                "Prefer 'agent_slug' to route to pre-configured agents."
            )

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
            "messages": msg_dicts,
            "temperature": temperature,
            "project_id": project_id,
            "enable_caching": enable_caching,
        }
        if agent_slug:
            payload["agent_slug"] = agent_slug
        if model:
            payload["model"] = model
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
        agent_slug: str | None = None,
        provider: str = "claude",
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 1.0,
        max_turns: int = 20,
        budget_tokens: int | None = None,
        thinking_level: str | None = None,
        enable_code_execution: bool = True,
        container_id: str | None = None,
        working_dir: str | None = None,
        timeout_seconds: float = 300.0,
        project_id: str = "agent-hub",
        use_memory: bool = True,
        memory_group_id: str | None = None,
    ) -> "AgentRunResponse":
        """Run an agent on a task with tool execution.

        For Claude: Uses code_execution sandbox for autonomous tool calling.
        For Gemini: Runs without tools (completion only).

        The agent will execute in a loop, calling tools as needed until the task
        is complete or max_turns is reached.

        Args:
            task: Task description for the agent.
            agent_slug: Agent slug for agent-based routing (e.g., "coder", "worker").
                When provided, loads agent config including model, mandates, and fallbacks.
                This is the PREFERRED way to configure agent execution.
            provider: LLM provider ("claude" or "gemini"). Overridden by agent_slug.
            model: Model override.
            system_prompt: Custom system prompt. Agent mandates are prepended when agent_slug is used.
            temperature: Sampling temperature.
            max_turns: Maximum agentic turns.
            budget_tokens: Extended thinking budget (Claude only).
            thinking_level: Thinking depth (minimal/low/medium/high/ultrathink). Claude only.
            enable_code_execution: Enable code execution sandbox (Claude only).
            container_id: Reuse existing container (Claude only).
            working_dir: Working directory for agent execution.
            timeout_seconds: Request timeout.
            project_id: Project ID for session tracking.
            use_memory: Inject memory context on first turn.
            memory_group_id: Memory group ID for isolation (defaults to project_id).

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
            "temperature": temperature,
            "max_turns": max_turns,
            "enable_code_execution": enable_code_execution,
            "timeout_seconds": timeout_seconds,
            "project_id": project_id,
            "use_memory": use_memory,
        }
        if agent_slug:
            payload["agent_slug"] = agent_slug
        if model:
            payload["model"] = model
        if system_prompt:
            payload["system_prompt"] = system_prompt
        if budget_tokens:
            payload["budget_tokens"] = budget_tokens
        if thinking_level:
            payload["thinking_level"] = thinking_level
        if container_id:
            payload["container_id"] = container_id
        if working_dir:
            payload["working_dir"] = working_dir
        if memory_group_id:
            payload["memory_group_id"] = memory_group_id

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

    def rate_episode(
        self,
        uuid: str,
        rating: str,
    ) -> dict[str, Any]:
        """Rate a memory episode for ACE-aligned feedback.

        Args:
            uuid: Episode UUID to rate.
            rating: Rating type ("helpful", "harmful", or "used").

        Returns:
            Dict with success status and message.

        Raises:
            ValidationError: If rating type is invalid.
            AgentHubError: For other errors.
        """
        client = self._get_client()

        payload = {"rating": rating}
        headers = self._inject_source_path()
        response = client.post(
            f"/api/memory/episodes/{uuid}/rating",
            json=payload,
            headers=headers,
        )

        if not response.is_success:
            _handle_error(response)

        return response.json()

    def save_learning(
        self,
        content: str,
        *,
        injection_tier: str = "reference",
        confidence: int = 80,
        context: str | None = None,
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """Save a learning to the memory system.

        Args:
            content: The learning content to save.
            injection_tier: Tier for injection priority ("mandate", "guardrail", "reference").
            confidence: Confidence level 0-100 (70+ provisional, 90+ canonical).
            context: Optional context about the learning source.
            scope: Memory scope ("global" or "project").
            scope_id: Scope identifier (e.g., project ID) when scope is "project".

        Returns:
            Dict with uuid, status, is_duplicate, reinforced_uuid, and message.

        Raises:
            ValidationError: If content validation fails.
            AgentHubError: For other errors.
        """
        client = self._get_client()

        payload: dict[str, Any] = {
            "content": content,
            "injection_tier": injection_tier,
            "confidence": confidence,
        }
        if context:
            payload["context"] = context

        headers = self._inject_source_path()
        if scope != "global":
            headers["X-Memory-Scope"] = scope
        if scope_id:
            headers["X-Scope-Id"] = scope_id

        response = client.post("/api/memory/save-learning", json=payload, headers=headers)

        if not response.is_success:
            _handle_error(response)

        return response.json()

    def list_episodes(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
        category: str | None = None,
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """List memory episodes with cursor-based pagination.

        Args:
            limit: Max episodes per page (1-100).
            cursor: Timestamp cursor for pagination.
            category: Filter by injection tier ("mandate", "guardrail", "reference").
            scope: Memory scope ("global" or "project").
            scope_id: Scope identifier when scope is "project".

        Returns:
            Dict with episodes list, total count, cursor, and has_more flag.

        Raises:
            AgentHubError: For errors.
        """
        client = self._get_client()

        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if category:
            params["category"] = category

        headers = self._inject_source_path()
        if scope != "global":
            headers["X-Memory-Scope"] = scope
        if scope_id:
            headers["X-Scope-Id"] = scope_id

        response = client.get("/api/memory/list", params=params, headers=headers)

        if not response.is_success:
            _handle_error(response)

        return response.json()

    def search_memories(
        self,
        query: str,
        *,
        limit: int = 10,
        min_score: float = 0.0,
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """Search memory for relevant episodes and facts.

        Args:
            query: Search query.
            limit: Max results (1-100).
            min_score: Minimum relevance score (0.0-1.0).
            scope: Memory scope ("global" or "project").
            scope_id: Scope identifier when scope is "project".

        Returns:
            Dict with query, results list, and count.

        Raises:
            AgentHubError: For errors.
        """
        client = self._get_client()

        params: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "min_score": min_score,
        }

        headers = self._inject_source_path()
        if scope != "global":
            headers["X-Memory-Scope"] = scope
        if scope_id:
            headers["X-Scope-Id"] = scope_id

        response = client.get("/api/memory/search", params=params, headers=headers)

        if not response.is_success:
            _handle_error(response)

        return response.json()

    def get_memory_stats(
        self,
        *,
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """Get memory statistics for the current group.

        Args:
            scope: Memory scope ("global" or "project").
            scope_id: Scope identifier when scope is "project".

        Returns:
            Dict with total, by_category list, by_scope list, last_updated, scope, and scope_id.

        Raises:
            AgentHubError: For errors.
        """
        client = self._get_client()

        headers = self._inject_source_path()
        if scope != "global":
            headers["X-Memory-Scope"] = scope
        if scope_id:
            headers["X-Scope-Id"] = scope_id

        response = client.get("/api/memory/stats", headers=headers)

        if not response.is_success:
            _handle_error(response)

        return response.json()


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
        client_id: str | None = None,
        client_secret: str | None = None,
        request_source: str | None = None,
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
            client_id: Client ID for access control authentication.
            client_secret: Client secret for access control authentication.
            request_source: Request source identifier for tracking.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.auto_inject_headers = auto_inject_headers
        self.client_id = client_id
        self.client_secret = client_secret
        self.request_source = request_source

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

            # Inject access control headers if credentials provided
            if self.client_id:
                headers["X-Client-Id"] = self.client_id
            if self.client_secret:
                headers["X-Client-Secret"] = self.client_secret
            if self.request_source:
                headers["X-Request-Source"] = self.request_source

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
        messages: list[dict[str, str] | MessageInput | ToolResultMessage],
        *,
        project_id: str,
        agent_slug: str | None = None,
        model: str | None = None,
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
            messages: Conversation messages (includes ToolResultMessage for tool results).
            project_id: Project ID for session tracking (required).
            agent_slug: Agent slug for routing (e.g., "coder", "planner"). When provided,
                loads agent config, injects mandates, and uses fallback chains. PREFERRED.
            model: DEPRECATED - Use agent_slug instead. Direct model specification.
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
            ValueError: If neither agent_slug nor model is provided.
        """
        # Validate: require agent_slug (preferred) or model (deprecated)
        if not agent_slug and not model:
            raise ValueError(
                "Either 'agent_slug' or 'model' must be provided. "
                "Prefer 'agent_slug' to route to pre-configured agents."
            )

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
            "messages": msg_dicts,
            "temperature": temperature,
            "project_id": project_id,
            "enable_caching": enable_caching,
        }
        if agent_slug:
            payload["agent_slug"] = agent_slug
        if model:
            payload["model"] = model
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

    async def stream_sse(
        self,
        messages: list[dict[str, str] | MessageInput],
        *,
        project_id: str,
        agent_slug: str | None = None,
        model: str | None = None,
        temperature: float = 1.0,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion using SSE (Server-Sent Events) via native API.

        Uses the native /api/complete endpoint with stream=true for
        full agent routing support including mandates and fallback chains.

        Args:
            messages: Conversation messages.
            project_id: Project ID for session tracking (required).
            agent_slug: Agent slug for routing (e.g., "coder", "planner"). PREFERRED.
            model: DEPRECATED - Use agent_slug instead. Direct model specification.
            temperature: Sampling temperature.

        Yields:
            StreamChunk for each streaming event.

        Raises:
            AgentHubError: If connection or streaming fails.
            ValueError: If neither agent_slug nor model is provided.
        """
        import json

        if not agent_slug and not model:
            raise ValueError(
                "Either 'agent_slug' or 'model' must be provided. "
                "Prefer 'agent_slug' to route to pre-configured agents."
            )

        client = await self._get_client()

        # Normalize messages
        msg_dicts = []
        for msg in messages:
            if isinstance(msg, MessageInput):
                msg_dicts.append(msg.model_dump())
            else:
                msg_dicts.append(msg)

        payload: dict[str, Any] = {
            "messages": msg_dicts,
            "project_id": project_id,
            "temperature": temperature,
            "stream": True,
        }
        if agent_slug:
            payload["agent_slug"] = agent_slug
        if model:
            payload["model"] = model

        headers = self._inject_source_path()
        try:
            async with client.stream("POST", "/api/complete", json=payload, headers=headers) as response:
                if not response.is_success:
                    await response.aread()
                    _handle_error(response)

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    if line.startswith("data: "):
                        data_str = line[6:]

                        if data_str == "[DONE]":
                            return

                        try:
                            data = json.loads(data_str)
                            event_type = data.get("type")

                            if event_type == "content":
                                yield StreamChunk(type="content", content=data.get("content", ""))

                            elif event_type == "done":
                                yield StreamChunk(
                                    type="done",
                                    finish_reason=data.get("finish_reason"),
                                    model=data.get("model"),
                                    provider=data.get("provider"),
                                    input_tokens=data.get("input_tokens"),
                                    output_tokens=data.get("output_tokens"),
                                    session_id=data.get("session_id"),
                                )
                                return

                            elif event_type == "error":
                                yield StreamChunk(type="error", error=data.get("error"))
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
        agent_slug: str | None = None,
        provider: str = "claude",
        model: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 1.0,
        max_turns: int = 20,
        budget_tokens: int | None = None,
        thinking_level: str | None = None,
        enable_code_execution: bool = True,
        container_id: str | None = None,
        working_dir: str | None = None,
        timeout_seconds: float = 300.0,
        project_id: str = "agent-hub",
        use_memory: bool = True,
        memory_group_id: str | None = None,
    ) -> "AgentRunResponse":
        """Run an agent on a task with tool execution.

        For Claude: Uses code_execution sandbox for autonomous tool calling.
        For Gemini: Runs without tools (completion only).

        The agent will execute in a loop, calling tools as needed until the task
        is complete or max_turns is reached.

        Args:
            task: Task description for the agent.
            agent_slug: Agent slug for agent-based routing (e.g., "coder", "worker").
                When provided, loads agent config including model, mandates, and fallbacks.
                This is the PREFERRED way to configure agent execution.
            provider: LLM provider ("claude" or "gemini"). Overridden by agent_slug.
            model: Model override.
            system_prompt: Custom system prompt. Agent mandates are prepended when agent_slug is used.
            temperature: Sampling temperature.
            max_turns: Maximum agentic turns.
            budget_tokens: Extended thinking budget (Claude only).
            thinking_level: Thinking depth (minimal/low/medium/high/ultrathink). Claude only.
            enable_code_execution: Enable code execution sandbox (Claude only).
            container_id: Reuse existing container (Claude only).
            working_dir: Working directory for agent execution.
            timeout_seconds: Request timeout.
            project_id: Project ID for session tracking.
            use_memory: Inject memory context on first turn.
            memory_group_id: Memory group ID for isolation (defaults to project_id).

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
            "temperature": temperature,
            "max_turns": max_turns,
            "enable_code_execution": enable_code_execution,
            "timeout_seconds": timeout_seconds,
            "project_id": project_id,
            "use_memory": use_memory,
        }
        if agent_slug:
            payload["agent_slug"] = agent_slug
        if model:
            payload["model"] = model
        if system_prompt:
            payload["system_prompt"] = system_prompt
        if budget_tokens:
            payload["budget_tokens"] = budget_tokens
        if thinking_level:
            payload["thinking_level"] = thinking_level
        if container_id:
            payload["container_id"] = container_id
        if working_dir:
            payload["working_dir"] = working_dir
        if memory_group_id:
            payload["memory_group_id"] = memory_group_id

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

    async def rate_episode(
        self,
        uuid: str,
        rating: str,
    ) -> dict[str, Any]:
        """Rate a memory episode for ACE-aligned feedback.

        Args:
            uuid: Episode UUID to rate.
            rating: Rating type ("helpful", "harmful", or "used").

        Returns:
            Dict with success status and message.

        Raises:
            ValidationError: If rating type is invalid.
            AgentHubError: For other errors.
        """
        client = await self._get_client()

        payload = {"rating": rating}
        headers = self._inject_source_path()
        response = await client.post(
            f"/api/memory/episodes/{uuid}/rating",
            json=payload,
            headers=headers,
        )

        if not response.is_success:
            _handle_error(response)

        return response.json()

    async def save_learning(
        self,
        content: str,
        *,
        injection_tier: str = "reference",
        confidence: int = 80,
        context: str | None = None,
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """Save a learning to the memory system.

        Args:
            content: The learning content to save.
            injection_tier: Tier for injection priority ("mandate", "guardrail", "reference").
            confidence: Confidence level 0-100 (70+ provisional, 90+ canonical).
            context: Optional context about the learning source.
            scope: Memory scope ("global" or "project").
            scope_id: Scope identifier (e.g., project ID) when scope is "project".

        Returns:
            Dict with uuid, status, is_duplicate, reinforced_uuid, and message.

        Raises:
            ValidationError: If content validation fails.
            AgentHubError: For other errors.
        """
        client = await self._get_client()

        payload: dict[str, Any] = {
            "content": content,
            "injection_tier": injection_tier,
            "confidence": confidence,
        }
        if context:
            payload["context"] = context

        headers = self._inject_source_path()
        if scope != "global":
            headers["X-Memory-Scope"] = scope
        if scope_id:
            headers["X-Scope-Id"] = scope_id

        response = await client.post("/api/memory/save-learning", json=payload, headers=headers)

        if not response.is_success:
            _handle_error(response)

        return response.json()

    async def list_episodes(
        self,
        *,
        limit: int = 50,
        cursor: str | None = None,
        category: str | None = None,
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """List memory episodes with cursor-based pagination.

        Args:
            limit: Max episodes per page (1-100).
            cursor: Timestamp cursor for pagination.
            category: Filter by injection tier ("mandate", "guardrail", "reference").
            scope: Memory scope ("global" or "project").
            scope_id: Scope identifier when scope is "project".

        Returns:
            Dict with episodes list, total count, cursor, and has_more flag.

        Raises:
            AgentHubError: For errors.
        """
        client = await self._get_client()

        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if category:
            params["category"] = category

        headers = self._inject_source_path()
        if scope != "global":
            headers["X-Memory-Scope"] = scope
        if scope_id:
            headers["X-Scope-Id"] = scope_id

        response = await client.get("/api/memory/list", params=params, headers=headers)

        if not response.is_success:
            _handle_error(response)

        return response.json()

    async def search_memories(
        self,
        query: str,
        *,
        limit: int = 10,
        min_score: float = 0.0,
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """Search memory for relevant episodes and facts.

        Args:
            query: Search query.
            limit: Max results (1-100).
            min_score: Minimum relevance score (0.0-1.0).
            scope: Memory scope ("global" or "project").
            scope_id: Scope identifier when scope is "project".

        Returns:
            Dict with query, results list, and count.

        Raises:
            AgentHubError: For errors.
        """
        client = await self._get_client()

        params: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "min_score": min_score,
        }

        headers = self._inject_source_path()
        if scope != "global":
            headers["X-Memory-Scope"] = scope
        if scope_id:
            headers["X-Scope-Id"] = scope_id

        response = await client.get("/api/memory/search", params=params, headers=headers)

        if not response.is_success:
            _handle_error(response)

        return response.json()

    async def get_memory_stats(
        self,
        *,
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, Any]:
        """Get memory statistics for the current group.

        Args:
            scope: Memory scope ("global" or "project").
            scope_id: Scope identifier when scope is "project".

        Returns:
            Dict with total, by_category list, by_scope list, last_updated, scope, and scope_id.

        Raises:
            AgentHubError: For errors.
        """
        client = await self._get_client()

        headers = self._inject_source_path()
        if scope != "global":
            headers["X-Memory-Scope"] = scope
        if scope_id:
            headers["X-Scope-Id"] = scope_id

        response = await client.get("/api/memory/stats", headers=headers)

        if not response.is_success:
            _handle_error(response)

        return response.json()

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
