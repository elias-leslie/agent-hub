"""Asynchronous client for Agent Hub API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx

from agent_hub._base import BaseClientMixin
from agent_hub._completion import build_completion_payload, handle_completion_response
from agent_hub._image import generate_image_async
from agent_hub._memory import AsyncMemoryOperationsMixin
from agent_hub._sessions import AsyncSessionOperationsMixin
from agent_hub._streaming import stream_completion_sse
from agent_hub.models import (
    CompletionResponse,
    ImageGenerationResponse,
    MessageInput,
    RoutingConfig,
    StreamChunk,
    ToolDefinition,
    ToolResultMessage,
)

if TYPE_CHECKING:
    from agent_hub.session import SessionContext


class AsyncAgentHubClient(
    BaseClientMixin,
    AsyncSessionOperationsMixin,
    AsyncMemoryOperationsMixin,
):
    """Asynchronous client for Agent Hub API.

    Example:
        async with AsyncAgentHubClient(
            base_url="http://localhost:8003",
            client_name="my-app"
        ) as client:
            response = await client.complete(
                model="claude-sonnet-4-6",
                messages=[{"role": "user", "content": "Hello!"}]
            )
            print(response.content)

            # Streaming
            async for chunk in client.stream(
                model="claude-sonnet-4-6",
                messages=[{"role": "user", "content": "Tell me a story"}]
            ):
                print(chunk.content, end="", flush=True)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8003",
        api_key: str | None = None,
        timeout: float | None = None,
        client_name: str | None = None,
        auto_inject_headers: bool = True,
        client_id: str | None = None,
        request_source: str | None = None,
        cli_command: str | None = None,
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
            request_source: Request source identifier for tracking.
            cli_command: CLI command name override for tool tracking.
                When set, this replaces the default SDK method name (e.g., "sdk.complete")
                in the X-Tool-Name header. Use this from CLI tools to track the actual
                command (e.g., "st memory save" instead of "sdk.save_learning").
        """
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            client_name=client_name,
            auto_inject_headers=auto_inject_headers,
            client_id=client_id,
            request_source=request_source,
            cli_command=cli_command,
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async httpx client."""
        if self._client is None:
            headers = self._build_base_headers()
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

    async def __aenter__(self) -> AsyncAgentHubClient:
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
        external_id: str | None = None,
        enable_caching: bool = True,
        use_memory: bool = False,
        memory_group_id: str | None = None,
        memory_variant_override: str | None = None,
        routing_config: RoutingConfig | dict[str, Any] | None = None,
        tools: list[dict[str, Any] | ToolDefinition] | None = None,
        enable_programmatic_tools: bool = False,
        container_id: str | None = None,
        max_turns: int = 1,
        working_dir: str | None = None,
        execute_tools: bool = False,
        task_type: str | None = None,
        trace_id: str | None = None,
        timeout_seconds: float | None = None,
        thinking_level: str | None = None,
        system_prompt: str | None = None,
        resume_session_id: str | None = None,
        include_roles: list[str] | None = None,
        current_branch: str | None = None,
        skip_cache: bool = False,
        response_format: dict[str, Any] | None = None,
        disable_agent_fallbacks: bool = False,
    ) -> CompletionResponse:
        """Generate a completion asynchronously. Use agent_slug for routing with mandates."""
        if not agent_slug and not model:
            raise ValueError(
                "Either 'agent_slug' or 'model' must be provided. "
                "Prefer 'agent_slug' to route to pre-configured agents."
            )

        self._check_disabled()

        client = await self._get_client()
        payload = build_completion_payload(
            messages=messages,
            project_id=project_id,
            agent_slug=agent_slug,
            model=model,
            temperature=temperature,
            session_id=session_id,
            purpose=purpose,
            external_id=external_id,
            enable_caching=enable_caching,
            use_memory=use_memory,
            memory_group_id=memory_group_id,
            memory_variant_override=memory_variant_override,
            routing_config=routing_config,
            tools=tools,
            enable_programmatic_tools=enable_programmatic_tools,
            container_id=container_id,
            max_turns=max_turns,
            working_dir=working_dir,
            execute_tools=execute_tools,
            task_type=task_type,
            trace_id=trace_id,
            timeout_seconds=timeout_seconds,
            thinking_level=thinking_level,
            system_prompt=system_prompt,
            resume_session_id=resume_session_id,
            include_roles=include_roles,
            current_branch=current_branch,
            skip_cache=skip_cache,
            response_format=response_format,
            disable_agent_fallbacks=disable_agent_fallbacks,
        )

        extra_headers = {"X-Skip-Cache": "true"} if skip_cache else None
        headers = self._inject_tracking_headers("sdk.complete", extra_headers=extra_headers)
        request_timeout = timeout_seconds if timeout_seconds is not None else self.timeout
        response = await client.post(
            "/api/complete", json=payload, headers=headers, timeout=request_timeout
        )

        return handle_completion_response(response, self)

    async def stream_sse(
        self,
        messages: list[dict[str, str] | MessageInput],
        *,
        project_id: str,
        agent_slug: str | None = None,
        model: str | None = None,
        temperature: float = 1.0,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion using SSE.

        Args:
            messages: Conversation messages.
            project_id: Project ID for session tracking.
            agent_slug: Agent slug for routing. PREFERRED.
            model: DEPRECATED - Use agent_slug instead.
            temperature: Sampling temperature.

        Yields:
            StreamChunk for each streaming event.
        """
        if not agent_slug and not model:
            raise ValueError(
                "Either 'agent_slug' or 'model' must be provided. "
                "Prefer 'agent_slug' to route to pre-configured agents."
            )

        client = await self._get_client()
        headers = self._inject_tracking_headers("sdk.stream_sse")

        async for chunk in stream_completion_sse(
            client=client,
            messages=messages,
            project_id=project_id,
            headers=headers,
            agent_slug=agent_slug,
            model=model,
            temperature=temperature,
        ):
            yield chunk

    async def generate_image(
        self,
        prompt: str,
        *,
        project_id: str,
        purpose: str | None = None,
        model: str = "gemini-3-pro-image-preview",
        size: str = "1024x1024",
        style: str | None = None,
        reference_image: str | None = None,
        reference_mime_type: str | None = None,
    ) -> ImageGenerationResponse:
        """Generate an image from a text prompt asynchronously."""
        client = await self._get_client()
        headers = self._inject_tracking_headers("sdk.generate_image")
        return await generate_image_async(
            client=client,
            headers=headers,
            prompt=prompt,
            project_id=project_id,
            purpose=purpose,
            model=model,
            size=size,
            style=style,
            reference_image=reference_image,
            reference_mime_type=reference_mime_type,
        )

    def session(
        self,
        project_id: str,
        provider: str,
        model: str,
        session_id: str | None = None,
    ) -> SessionContext:
        """Create a session context manager for automatic conversation tracking."""
        from agent_hub.session import SessionContext

        return SessionContext(
            client=self,
            project_id=project_id,
            provider=provider,
            model=model,
            session_id=session_id,
        )
