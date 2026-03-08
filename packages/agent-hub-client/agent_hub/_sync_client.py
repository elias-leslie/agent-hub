"""Synchronous client for Agent Hub API."""

from __future__ import annotations

from typing import Any

import httpx

from agent_hub._base import BaseClientMixin
from agent_hub._completion import build_completion_payload, handle_completion_response
from agent_hub._image import generate_image_sync
from agent_hub._memory import MemoryOperationsMixin
from agent_hub._sessions import SessionOperationsMixin
from agent_hub.models import (
    CompletionResponse,
    ImageGenerationResponse,
    MessageInput,
    RoutingConfig,
    ToolDefinition,
    ToolResultMessage,
)


class AgentHubClient(
    BaseClientMixin,
    SessionOperationsMixin,
    MemoryOperationsMixin,
):
    """Synchronous client for Agent Hub API.

    Example:
        client = AgentHubClient(
            base_url="http://localhost:8003",
            client_name="my-app"
        )
        response = client.complete(
            model="claude-sonnet-4-6",
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
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Get or create httpx client."""
        if self._client is None:
            headers = self._build_base_headers()
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
        routing_config: RoutingConfig | dict[str, Any] | None = None,
        tools: list[dict[str, Any] | ToolDefinition] | None = None,
        enable_programmatic_tools: bool = False,
        container_id: str | None = None,
        max_turns: int = 1,
        working_dir: str | None = None,
        execute_tools: bool = False,
        trace_id: str | None = None,
        timeout_seconds: float | None = None,
        thinking_level: str | None = None,
        system_prompt: str | None = None,
        resume_session_id: str | None = None,
        include_roles: list[str] | None = None,
        current_branch: str | None = None,
    ) -> CompletionResponse:
        """Generate a completion. Use agent_slug for routing with mandates and fallbacks."""
        if not agent_slug and not model:
            raise ValueError(
                "Either 'agent_slug' or 'model' must be provided. "
                "Prefer 'agent_slug' to route to pre-configured agents."
            )

        self._check_disabled()

        client = self._get_client()
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
            routing_config=routing_config,
            tools=tools,
            enable_programmatic_tools=enable_programmatic_tools,
            container_id=container_id,
            max_turns=max_turns,
            working_dir=working_dir,
            execute_tools=execute_tools,
            trace_id=trace_id,
            timeout_seconds=timeout_seconds,
            thinking_level=thinking_level,
            system_prompt=system_prompt,
            resume_session_id=resume_session_id,
            include_roles=include_roles,
            current_branch=current_branch,
        )

        headers = self._inject_tracking_headers("sdk.complete")
        # HTTP timeout must cover all turns. The server enforces per-turn inactivity
        # timeout internally — the SDK just needs a generous ceiling so the HTTP
        # connection doesn't drop while the agent is still making progress.
        if timeout_seconds and max_turns > 1:
            request_timeout = timeout_seconds * max_turns + 60
        elif timeout_seconds:
            request_timeout = timeout_seconds + 30
        else:
            request_timeout = self.timeout
        response = client.post(
            "/api/complete", json=payload, headers=headers, timeout=request_timeout
        )

        return handle_completion_response(response, self)

    def generate_image(
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
        """Generate an image from a text prompt."""
        client = self._get_client()
        headers = self._inject_tracking_headers("sdk.generate_image")
        return generate_image_sync(
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
