"""Mixin providing tool-session methods for ClaudeAdapter.

Extracted from claude.py to keep that module under 200 lines.  All
public interfaces (method signatures, return types) are identical.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from app.adapters.base import Message, ProviderRuntimeSession

if TYPE_CHECKING:
    pass


class ClaudeToolSessionMixin:
    """Mixin that adds tool-calling and session methods to ClaudeAdapter.

    Expects the host class to provide:
      - ``self._cli_path``  - path to the ``claude`` binary (or None)
      - ``self._use_direct_api`` - bool property
      - ``self.MODEL_MAP``  - dict mapping model names to SDK short names
      - ``self.provider_name`` - str
    """

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        working_dir: str | None = None,
        resume_session_id: str | None = None,
        max_turns: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        """Generate with native tool calling. Yields (SDK message, session_id).

        Tool calling requires the CLI — direct API doesn't support agentic tool use
        with Max subscription OAuth tokens.
        """
        from app.adapters.claude_tools_helpers import complete_with_tools as _complete_with_tools

        assert self._cli_path is not None  # type: ignore[attr-defined]
        async for message in _complete_with_tools(
            messages=messages,
            model=model,
            tools=tools,
            working_dir=working_dir,
            resume_session_id=resume_session_id,
            cli_path=self._cli_path,  # type: ignore[attr-defined]
            model_map=self.MODEL_MAP,  # type: ignore[attr-defined]
            provider_name=self.provider_name,  # type: ignore[attr-defined]
            max_turns=max_turns,
            **kwargs,
        ):
            yield message

    def complete_with_tool_events(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        working_dir: str | None,
        max_turns: int,
        project_id: str | None,
        session_id: str,
        agent_slug: str | None,
        tool_catalog: list[dict[str, Any]] | None,
    ) -> AsyncIterator[tuple[Any, str]]:
        """Return canonical ToolEvents for the shared tool execution pipeline."""
        del session_id  # Claude SDK emits its own session id stream.
        del project_id
        from app.adapters.claude_tool_events import adapt_claude_stream

        raw_stream = self.complete_with_tools(
            messages=messages,
            model=model,
            tools=tools,
            working_dir=working_dir,
            max_turns=max_turns,
            agent_slug=agent_slug,
            tool_catalog=tool_catalog,
        )
        return adapt_claude_stream(raw_stream)

    async def start_tool_session(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        working_dir: str | None,
        max_turns: int,
        project_id: str | None,
        session_id: str,
        agent_slug: str | None,
        tool_catalog: list[dict[str, Any]] | None,
    ) -> ProviderRuntimeSession:
        """Start an owned Claude runtime session for one tool turn."""
        if self._use_direct_api:  # type: ignore[attr-defined]
            return await super().start_tool_session(  # type: ignore[misc]
                messages=messages,
                model=model,
                tools=tools,
                working_dir=working_dir,
                max_turns=max_turns,
                project_id=project_id,
                session_id=session_id,
                agent_slug=agent_slug,
                tool_catalog=tool_catalog,
            )

        from app.adapters.claude_tools_helpers import (
            build_tool_runtime_session as _build_tool_runtime_session,
        )

        assert self._cli_path is not None  # type: ignore[attr-defined]
        return await _build_tool_runtime_session(
            messages=messages,
            model=model,
            tools=tools,
            working_dir=working_dir,
            resume_session_id=None,
            cli_path=self._cli_path,  # type: ignore[attr-defined]
            model_map=self.MODEL_MAP,  # type: ignore[attr-defined]
            provider_name=self.provider_name,  # type: ignore[attr-defined]
            max_turns=max_turns,
            project_id=project_id,
            session_id=session_id,
            agent_slug=agent_slug,
            tool_catalog=tool_catalog,
        )
