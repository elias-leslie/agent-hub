"""CloudCode Claude adapter — Claude models via Google CloudCode PA (zero-cost).

Uses ``cloudcode-pa.googleapis.com`` with Antigravity OAuth credentials.
Requires a separate OAuth flow (different client ID + cclog/experimentsandconfigs
scopes). Provides free access to Claude Sonnet 4.6 and Opus 4.6 (thinking)
via a Google One AI Pro / Gemini Code Assist subscription.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import CompletionResult, Message, ProviderAdapter, StreamEvent
from app.adapters.cloudcode_claude_auth import make_cc_client, resolve_antigravity_oauth
from app.adapters.cloudcode_claude_streaming import run_tool_loop, stream_generate
from app.adapters.cloudcode_claude_transforms import (
    append_thinking_hint,
    build_claude_generation_config,
    build_claude_tool_config,
    ensure_antigravity_system_instruction,
    is_thinking_model,
    resolve_cloudcode_model,
)
from app.adapters.cloudcode_client import (
    CloudCodeClient,
    build_cloudcode_tools,
    convert_messages_for_cloudcode,
    parse_cloudcode_response,
)
from app.services.tools.direct_executor import create_direct_handler

logger = logging.getLogger(__name__)

# (resolved_model, sys_inst, contents, gen_config, tools, tool_config)
_RequestParams = tuple[
    str,
    dict[str, Any] | None,
    list[dict[str, Any]],
    dict[str, Any] | None,
    list[dict[str, Any]] | None,
    dict[str, Any] | None,
]


class CloudCodeClaudeAdapter(ProviderAdapter):
    """Adapter for Claude models via Google CloudCode PA endpoint."""

    provider_name = "cloudcode"

    def __init__(self) -> None:
        self._cc_client: CloudCodeClient | None = None

    def _ensure_client(self) -> CloudCodeClient:
        """Get or create a CloudCodeClient, refreshing credentials if needed."""
        if self._cc_client is None:
            self._cc_client = make_cc_client()
        else:
            self._refresh_credentials()
        if self._cc_client is None:
            from app.adapters.base import AuthenticationError
            raise AuthenticationError(provider="cloudcode")
        return self._cc_client

    def _apply_credential_data(self, data: dict[str, Any]) -> None:
        """Write resolved OAuth fields onto the cached client."""
        if self._cc_client is None:
            return
        # Don't override project_id — keep synthetic ID
        for key, attr in (
            ("access_token", "access_token"),
            ("refresh_token", "refresh_token"),
            ("expires_at", "expires_at"),
        ):
            if data.get(key):
                setattr(self._cc_client, attr, data[key])

    def _refresh_credentials(self) -> None:
        """Update client credentials from the credential manager."""
        try:
            data = resolve_antigravity_oauth()
            if data:
                self._apply_credential_data(data)
        except Exception:
            logger.debug("CloudCode Claude: credential refresh failed", exc_info=True)

    def _prepare_request(
        self,
        messages: list[Message],
        model: str,
        temperature: float = 1.0,
        max_tokens: int | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> _RequestParams:
        """Build all request parameters for a Claude CloudCode call."""
        kwargs = kwargs or {}
        resolved = resolve_cloudcode_model(model)
        system_instruction, contents = convert_messages_for_cloudcode(messages)
        system_instruction = ensure_antigravity_system_instruction(system_instruction)
        generation_config = build_claude_generation_config(
            thinking_level=kwargs.get("thinking_level"),
            max_tokens=max_tokens,
            temperature=temperature,
            model=resolved,
        )
        tools = None
        tool_config = None
        if kwargs.get("tools"):
            tools = build_cloudcode_tools(kwargs["tools"])
            tool_config = build_claude_tool_config()
            if is_thinking_model(resolved):
                system_instruction = append_thinking_hint(system_instruction)
        return resolved, system_instruction, contents, generation_config, tools, tool_config

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        """Non-streaming completion via CloudCode PA with Claude model."""
        client = self._ensure_client()
        r, si, co, gc, tl, tc = self._prepare_request(messages, model, temperature, max_tokens, kwargs)
        data = await client.generate_content(
            model=r, contents=co, system_instruction=si,
            generation_config=gc, tools=tl, tool_config=tc,
        )
        return parse_cloudcode_response(data, model, self.provider_name)

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream completion via CloudCode PA SSE with Claude model."""
        client = self._ensure_client()
        r, si, co, gc, tl, tc = self._prepare_request(messages, model, temperature, max_tokens, kwargs)
        async for event in stream_generate(client, r, co, si, gc, tl, tc):
            yield event

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        working_dir: str | None = None,
        max_tokens: int | None = None,
        max_turns: int = 20,
        project_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        """Run agentic tool loop via CloudCode PA with Claude model."""
        client = self._ensure_client()
        resolved = resolve_cloudcode_model(model)
        tool_handler = create_direct_handler(
            working_dir, kwargs.get("permission_config"), project_id=project_id,
            tool_catalog=kwargs.get("tool_catalog"),
        )
        session_id = str(uuid.uuid4())
        system_instruction, contents = convert_messages_for_cloudcode(messages)
        system_instruction = ensure_antigravity_system_instruction(system_instruction)
        cc_tools = build_cloudcode_tools(tools)
        tool_config = build_claude_tool_config()
        if is_thinking_model(resolved):
            system_instruction = append_thinking_hint(system_instruction)
        async for event in run_tool_loop(
            client=client,
            resolved=resolved,
            contents=contents,
            system_instruction=system_instruction,
            cc_tools=cc_tools,
            tool_config=tool_config,
            thinking_level=kwargs.get("thinking_level"),
            max_tokens=max_tokens,
            max_turns=max_turns,
            tool_handler=tool_handler,
            session_id=session_id,
        ):
            yield event

    async def health_check(self) -> bool:
        """Check if CloudCode PA credentials are valid (zero tokens consumed)."""
        try:
            client = self._ensure_client()
            await client._ensure_token()
            return bool(client.access_token)
        except Exception as e:
            logger.warning("CloudCode Claude health check failed: %s", e)
            return False
