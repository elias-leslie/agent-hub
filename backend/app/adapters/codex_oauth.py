"""Codex OAuth adapter -- ChatGPT subscription-based OpenAI access.

Uses the ChatGPT backend Responses API (``/backend-api/codex/responses``)
with OAuth bearer tokens from a ChatGPT Plus/Pro subscription.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, suppress
from pathlib import Path
from typing import Any

import httpx

from app.adapters._openai_compat_helpers import normalize_responses_content
from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    Message,
    ProviderAdapter,
    ProviderError,
    StreamEvent,
)
from app.adapters.codex_auth import (
    CodexCredentials,
    extract_account_id,
    parse_stored_oauth_token,
    refresh_access_token,
    serialize_stored_oauth_token,
)
from app.adapters.codex_sse import (
    CODEX_API_URL,
    DEFAULT_TIMEOUT,
    build_headers,
    build_request_body,
    collect_completion,
    handle_error_response,
    iter_stream_events,
)
from app.adapters.codex_token_cache import read_cached_token, write_cached_token

logger = logging.getLogger(__name__)
_EMPTY_FINAL_RESPONSE_MSG = (
    "You have finished tool work but have not produced a final user-facing response. "
    "Write the final response now. "
    "If no changes were needed, say so plainly. "
    "If changes were made, summarize the exact changes and evidence. "
    "Do not call more tools unless a missing fact blocks the response."
)

ToolHandler = Callable[[str, dict[str, Any]], Awaitable[str]]
_DEFAULT_CODEX_AUTH_PATH = Path("~/.codex/auth.json").expanduser()


def load_local_codex_auth_credentials(path: str | Path | None = None) -> CodexCredentials | None:
    """Return Codex credentials from the local Codex auth file when available."""
    raw_path = path or os.environ.get("AGENT_HUB_CODEX_AUTH_FILE")
    auth_path = Path(raw_path).expanduser() if raw_path else _DEFAULT_CODEX_AUTH_PATH

    try:
        payload = json.loads(auth_path.read_text())
    except FileNotFoundError:
        return None
    except Exception:
        logger.warning("Failed to read local Codex auth file", exc_info=True)
        return None

    if not isinstance(payload, dict):
        return None
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        return None

    raw_access_token = tokens.get("access_token")
    if not isinstance(raw_access_token, str) or not raw_access_token:
        return None

    access_token, expires_at = parse_stored_oauth_token(raw_access_token)
    if not access_token:
        return None

    try:
        account_id = extract_account_id(access_token)
    except ValueError:
        logger.warning("Failed to parse local Codex access token", exc_info=True)
        return None

    refresh_token = tokens.get("refresh_token")
    return CodexCredentials(
        access_token=access_token,
        refresh_token=refresh_token if isinstance(refresh_token, str) and refresh_token else None,
        account_id=account_id,
        expires_at=expires_at,
    )


def _cancelled_done_event(total_content: str) -> StreamEvent:
    return StreamEvent(
        type="done",
        input_tokens=0,
        output_tokens=len(total_content) // 4,
        finish_reason="cancelled",
    )


def _is_abort_event(value: object) -> bool:
    return isinstance(value, asyncio.Event)


def _abort_requested(abort_event: asyncio.Event | None) -> bool:
    return abort_event is not None and abort_event.is_set()


def _is_benign_interrupt_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.ReadError, httpx.StreamClosed)):
        return True
    message = str(exc).lower()
    return any(snippet in message for snippet in (
        "stream closed",
        "connection closed",
        "closed resource",
        "response stream consumed",
    ))


def _resolve_model(model: str) -> str:
    """Strip the ``codex/`` prefix if present."""
    return model[len("codex/"):] if model.startswith("codex/") else model


def _convert_messages_to_input(messages: list[Message]) -> tuple[list[dict[str, Any]], str | None]:
    """Convert internal Message objects to Responses API ``input`` format.

    System messages become ``instructions`` at the top level.
    """
    instructions: str | None = None
    input_items: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "system":
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            instructions = f"{instructions}\n{text}" if instructions else text
            continue
        input_items.append({"role": msg.role, "content": normalize_responses_content(msg.role, msg.content)})
    return input_items, instructions


def _assistant_text_item(content: str, turn: int) -> dict[str, Any]:
    return {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": content, "annotations": []}],
        "status": "completed",
        "id": f"msg_{turn}",
    }


def _assistant_tool_call_item(tool_id: str, name: str, arguments: dict[str, Any], turn: int) -> dict[str, Any]:
    return {
        "type": "function_call",
        "id": f"fc_{turn}_{tool_id}".replace("-", "_"),
        "call_id": tool_id,
        "name": name,
        "arguments": json.dumps(arguments),
    }


def _tool_result_item(tool_id: str, output: str) -> dict[str, Any]:
    return {"type": "function_call_output", "call_id": tool_id, "output": output}


def _user_text_item(content: str) -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "input_text", "text": content}]}


async def _watch_and_interrupt(abort_event: asyncio.Event, session: _CodexResponseSession) -> None:
    await abort_event.wait()
    await session.interrupt()


async def _dispatch_tool_calls(
    input_items: list[dict[str, Any]],
    tool_calls: list[Any],
    tool_handler: ToolHandler,
    turn: int,
) -> AsyncIterator[StreamEvent]:
    for tool_call in tool_calls:
        input_items.append(_assistant_tool_call_item(tool_call.id, tool_call.name, tool_call.input, turn))
        yield StreamEvent(type="tool_use", tool_id=tool_call.id, tool_name=tool_call.name, tool_input=tool_call.input)
        try:
            tool_result_str = await tool_handler(tool_call.name, tool_call.input)
        except Exception as exc:
            logger.error("Tool handler raised an exception for %r: %s", tool_call.name, exc)
            yield StreamEvent(type="error", error=str(exc))
            return
        yield StreamEvent(type="tool_result", tool_id=tool_call.id, content=tool_result_str)
        input_items.append(_tool_result_item(tool_call.id, tool_result_str))


class _CodexResponseSession:
    """Own the HTTP client and SSE response lifetime for one Codex request."""

    def __init__(
        self,
        *,
        body: dict[str, Any],
        headers: dict[str, str],
        request_timeout: float | None = DEFAULT_TIMEOUT,
    ) -> None:
        self.body = body
        self.headers = headers
        self.request_timeout = request_timeout
        self.response: httpx.Response | None = None
        self._exit_stack = AsyncExitStack()
        self._closed = False

    async def start(self) -> None:
        """Open the owned client + stream response and validate status."""
        client = await self._exit_stack.enter_async_context(httpx.AsyncClient(timeout=self.request_timeout))
        self.response = await self._exit_stack.enter_async_context(
            client.stream("POST", CODEX_API_URL, json=self.body, headers=self.headers)
        )
        if self.response.status_code != 200:
            error_body = await self.response.aread()
            await self.close()
            handle_error_response(
                self.response.status_code,
                error_body.decode("utf-8", errors="replace"),
            )

    async def interrupt(self) -> None:
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with suppress(asyncio.CancelledError, RuntimeError, httpx.StreamError):
            await self._exit_stack.aclose()


class CodexOAuthAdapter(ProviderAdapter):
    """Adapter for OpenAI models via the ChatGPT backend API (OAuth, subscription billing).

    Authenticates via OAuth tokens from a ChatGPT Plus/Pro subscription.
    Endpoint: ``https://chatgpt.com/backend-api/codex/responses``
    """

    provider_name = "codex"

    def __init__(self, credentials: CodexCredentials | None = None) -> None:
        self._credentials = credentials
        self._credentials_override = credentials is not None
        self._refresh_lock = asyncio.Lock()
        # Eagerly verify credentials exist so the registry/prober can skip
        # this provider when unconfigured, rather than deferring to health_check.
        if credentials is None:
            self._get_credentials()

    def _load_credentials_from_manager(self) -> CodexCredentials | None:
        try:
            from app.services.credential_manager import get_credential_manager

            cm = get_credential_manager()
            if cm.is_initialized:
                token_value = cm.get("codex", "oauth_token") or cm.get_api_key("codex")
                refresh = cm.get("codex", "refresh_token")
                access_token, expires_at = parse_stored_oauth_token(token_value)
                if access_token:
                    return CodexCredentials(
                        access_token=access_token,
                        refresh_token=refresh,
                        account_id=extract_account_id(access_token),
                        expires_at=expires_at,
                    )
        except Exception:
            logger.warning("Failed to resolve Codex credentials from cache", exc_info=True)
        return None

    def _get_credentials(self) -> CodexCredentials:
        if self._credentials_override and self._credentials is not None:
            return self._credentials

        creds = self._load_credentials_from_manager()
        if creds is not None:
            self._credentials = creds
            return creds

        if self._credentials is not None:
            return self._credentials
        raise AuthenticationError(provider="codex")

    async def _reload_credentials_from_db(self) -> CodexCredentials | None:
        """Reload the credential manager from DB and return the latest Codex creds."""
        if self._credentials_override:
            return self._credentials

        try:
            from app.db import async_session
            from app.services.credential_manager import get_credential_manager

            cm = get_credential_manager()
            async with async_session() as db:
                await cm.load(db)
        except Exception:
            logger.warning("Failed to reload Codex credentials from DB", exc_info=True)
            return None

        creds = self._load_credentials_from_manager()
        if creds is not None:
            self._credentials = creds
        return creds

    async def _persist_credentials(self, credentials: CodexCredentials) -> None:
        """Persist refreshed Codex credentials to cache and DB."""
        token_value = serialize_stored_oauth_token(credentials)

        try:
            from app.services.credential_manager import get_credential_manager

            cm = get_credential_manager()
            cm.set("codex", "oauth_token", token_value)
            if credentials.refresh_token:
                cm.set("codex", "refresh_token", credentials.refresh_token)
        except Exception:
            logger.warning("Failed to update Codex credentials in cache", exc_info=True)

        try:
            from app.db import async_session
            from app.services.credential_upsert import upsert_credential

            async with async_session() as db:
                await upsert_credential(db, "codex", "oauth_token", token_value)
                if credentials.refresh_token:
                    await upsert_credential(db, "codex", "refresh_token", credentials.refresh_token)
        except Exception:
            logger.warning("Failed to persist refreshed Codex token to DB", exc_info=True)

    async def _ensure_fresh_credentials(self) -> CodexCredentials:
        creds = self._get_credentials()
        if not creds.is_expired:
            return creds
        if not creds.refresh_token:
            reloaded = await self._reload_credentials_from_db()
            if reloaded is not None:
                creds = reloaded
            if not creds.refresh_token:
                raise AuthenticationError(provider="codex")
            if not creds.is_expired:
                return creds
        async with self._refresh_lock:
            creds = self._get_credentials()
            if not creds.is_expired:
                return creds
            if not creds.refresh_token:
                raise AuthenticationError(provider="codex")
            logger.info("Codex access token expired, refreshing...")
            try:
                cached = await asyncio.to_thread(read_cached_token, creds.refresh_token)
                new_creds = cached if cached is not None else await refresh_access_token(creds.refresh_token)
                if cached is None:
                    await asyncio.to_thread(write_cached_token, new_creds)
                await self._persist_credentials(new_creds)
                self._credentials = new_creds
                return new_creds
            except Exception as exc:
                logger.warning("Codex token refresh failed", exc_info=True)
                reloaded = await self._reload_credentials_from_db()
                if reloaded is not None:
                    current_pair = (creds.access_token, creds.refresh_token)
                    reloaded_pair = (reloaded.access_token, reloaded.refresh_token)
                    if reloaded_pair != current_pair or not reloaded.is_expired:
                        logger.info("Recovered Codex credentials from DB after refresh failure")
                        return reloaded
                local_creds = load_local_codex_auth_credentials()
                if local_creds is not None:
                    current_pair = (creds.access_token, creds.refresh_token)
                    local_pair = (local_creds.access_token, local_creds.refresh_token)
                    if local_pair != current_pair or not local_creds.is_expired:
                        logger.info("Recovered Codex credentials from local auth file after refresh failure")
                        await self._persist_credentials(local_creds)
                        self._credentials = local_creds
                        return local_creds
                raise AuthenticationError(provider="codex") from exc

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate a non-streaming completion via the Codex Responses API."""
        from app.adapters.errors import with_retry

        @with_retry
        async def _do_complete() -> CompletionResult:
            resolved_model = _resolve_model(model)
            input_items, instructions = _convert_messages_to_input(messages)
            return await self._complete_from_input(
                input_items=input_items,
                instructions=instructions,
                resolved_model=resolved_model,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )

        return await _do_complete()

    async def _complete_from_input(
        self,
        *,
        input_items: list[dict[str, Any]],
        instructions: str | None,
        resolved_model: str,
        max_tokens: int | None,
        temperature: float,
        request_timeout: float | None = DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> CompletionResult:
        creds = await self._ensure_fresh_credentials()
        body = build_request_body(
            input_items,
            resolved_model,
            instructions=instructions,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )
        headers = build_headers(creds)
        session = _CodexResponseSession(body=body, headers=headers, request_timeout=request_timeout)
        try:
            await session.start()
            if session.response is None:
                raise RuntimeError("Codex response session did not initialize a response")
            try:
                return await collect_completion(session.response, resolved_model)
            finally:
                await session.close()
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.ReadError, httpx.ConnectError) as exc:
            logger.error("Codex HTTP error: %s", exc)
            raise ProviderError(str(exc), provider="codex", retriable=True) from exc

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream completion tokens from the Codex Responses API."""
        creds = await self._ensure_fresh_credentials()
        input_items, instructions = _convert_messages_to_input(messages)
        body = build_request_body(
            input_items,
            _resolve_model(model),
            instructions=instructions,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )
        headers = build_headers(creds)
        abort_event = kwargs.get("abort_event")
        owned_abort_event = abort_event if _is_abort_event(abort_event) else None
        session = _CodexResponseSession(body=body, headers=headers)
        total_content = ""
        abort_watch_task: asyncio.Task[None] | None = None

        try:
            if _abort_requested(owned_abort_event):
                yield _cancelled_done_event(total_content)
                return

            await session.start()
            if owned_abort_event is not None:
                abort_watch_task = asyncio.create_task(_watch_and_interrupt(owned_abort_event, session))

            if session.response is None:
                raise RuntimeError("Codex stream session did not initialize a response")

            async for event in iter_stream_events(session.response):
                if event.type == "content":
                    total_content += event.content or ""
                if _abort_requested(owned_abort_event):
                    raise asyncio.CancelledError("Abort signal received")
                yield event
        except asyncio.CancelledError:
            logger.warning("Codex stream cancelled (cancel scope); emitting cancelled done")
            yield _cancelled_done_event(total_content)
        except (httpx.HTTPStatusError, httpx.ReadError, httpx.ConnectError, httpx.StreamError, RuntimeError) as exc:
            if _abort_requested(owned_abort_event) and _is_benign_interrupt_error(exc):
                logger.warning("Codex stream interrupted during cancellation; emitting cancelled done")
                yield _cancelled_done_event(total_content)
                return
            logger.error("Codex stream HTTP error: %s", exc)
            yield StreamEvent(type="error", error=str(exc))
        finally:
            if abort_watch_task is not None:
                abort_watch_task.cancel()
                with suppress(asyncio.CancelledError):
                    await abort_watch_task
            await session.close()

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        tool_handler: ToolHandler,
        max_turns: int = 20,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Run a tool-calling loop over the Codex Responses API."""
        kwargs = kwargs.copy()
        temperature: float = kwargs.pop("temperature", 1.0)
        max_tokens: int | None = kwargs.pop("max_tokens", None)
        prompt_cache_key = kwargs.pop("prompt_cache_key", None) or str(uuid.uuid4())
        input_items, instructions = _convert_messages_to_input(messages)
        resolved_model = _resolve_model(model)
        total_input_tokens = 0
        total_output_tokens = 0
        empty_closeout_used = False

        for turn in range(max_turns):
            result = await self._complete_from_input(
                input_items=input_items,
                instructions=instructions,
                resolved_model=resolved_model,
                max_tokens=max_tokens,
                temperature=temperature,
                request_timeout=None,
                tools=tools,
                prompt_cache_key=prompt_cache_key,
                **kwargs,
            )
            total_input_tokens += result.input_tokens or 0
            total_output_tokens += result.output_tokens or 0

            if result.thinking_content:
                yield StreamEvent(type="thinking", content=result.thinking_content)
            if result.content:
                yield StreamEvent(type="content", content=result.content)

            if not result.tool_calls:
                if not (result.content or "").strip() and not empty_closeout_used and turn + 1 < max_turns:
                    input_items.append(_user_text_item(_EMPTY_FINAL_RESPONSE_MSG))
                    empty_closeout_used = True
                    continue
                yield StreamEvent(
                    type="done",
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    finish_reason=result.finish_reason,
                )
                return

            if result.content:
                input_items.append(_assistant_text_item(result.content, turn))

            async for event in _dispatch_tool_calls(input_items, result.tool_calls, tool_handler, turn):
                yield event
                if event.type == "error":
                    return

        yield StreamEvent(type="done", finish_reason="max_turns")

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
        from app.adapters.openai_tool_events import adapt_openai_stream

        return adapt_openai_stream(
            self,
            messages,
            model,
            tools,
            working_dir,
            max_turns,
            project_id,
            session_id,
            agent_slug=agent_slug,
            tool_catalog=tool_catalog,
        )

    async def health_check(self) -> bool:
        """Check if Codex credentials are valid (zero tokens consumed)."""
        try:
            creds = await self._ensure_fresh_credentials()
            return bool(creds and creds.access_token)
        except Exception:
            return False
