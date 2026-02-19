"""Codex OAuth adapter -- ChatGPT subscription-based OpenAI access.

Uses the ChatGPT backend Responses API (``/backend-api/codex/responses``)
with OAuth bearer tokens from a ChatGPT Plus/Pro subscription.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
from filelock import FileLock

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    Message,
    ProviderAdapter,
    ProviderError,
    RateLimitError,
    StreamEvent,
)
from app.adapters.codex_auth import (
    CodexCredentials,
    extract_account_id,
    refresh_access_token,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CODEX_API_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_TIMEOUT = 120.0  # seconds

# File-based lock for coordinating token refresh across concurrent workers
_TOKEN_LOCK_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
_TOKEN_LOCK_PATH = _TOKEN_LOCK_DIR / "agent-hub-codex-token.lock"
_TOKEN_CACHE_PATH = _TOKEN_LOCK_DIR / "agent-hub-codex-token.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _convert_messages_to_input(messages: list[Message]) -> tuple[list[dict[str, Any]], str | None]:
    """Convert internal Message objects to Responses API ``input`` format.

    The Responses API uses ``input`` (not ``messages``), with the same
    ``{role, content}`` shape.  System messages become ``instructions``
    at the top level, so we filter them out here and return them separately.
    """
    instructions: str | None = None
    input_items: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == "system":
            # Accumulate system messages into instructions
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            instructions = f"{instructions}\n{text}" if instructions else text
            continue
        input_items.append({"role": msg.role, "content": msg.content})

    return input_items, instructions


def _build_headers(credentials: CodexCredentials) -> dict[str, str]:
    """Build request headers for the Codex backend API."""
    return {
        "Authorization": f"Bearer {credentials.access_token}",
        "chatgpt-account-id": credentials.account_id,
        "Content-Type": "application/json",
        "OpenAI-Beta": "responses=experimental",
        "Accept": "text/event-stream",
        "originator": "agent-hub",
    }


def _build_request_body(
    input_items: list[dict[str, Any]],
    model: str,
    *,
    instructions: str | None = None,
    temperature: float = 1.0,
    max_tokens: int | None = None,
    stream: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build the JSON body for a Codex Responses API request."""
    body: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "stream": stream,
        "store": False,
    }

    if instructions:
        body["instructions"] = instructions

    if temperature != 1.0:
        body["temperature"] = temperature

    if max_tokens is not None:
        body["max_output_tokens"] = max_tokens

    # Forward recognised extra kwargs
    if kwargs.get("reasoning_effort"):
        body["reasoning"] = {"effort": kwargs["reasoning_effort"], "summary": "auto"}

    return body


def _secure_write(path: Path, data: str) -> None:
    """Write *data* to *path* with owner-only (0o600) permissions.

    Uses low-level os.open() so the file is created with restricted
    permissions from the start, avoiding a window where world-readable
    permissions could be inherited from the default umask.
    """
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(data)


def _handle_error_response(status_code: int, body_text: str) -> None:
    """Raise the appropriate ProviderError subclass based on HTTP status and body."""
    # Try to parse error JSON
    error_code = ""
    error_message = body_text
    try:
        data = json.loads(body_text)
        err = data.get("error", {})
        error_code = err.get("code") or err.get("type") or ""
        error_message = err.get("message") or body_text
    except (json.JSONDecodeError, AttributeError):
        pass

    if status_code == 429 or "usage_limit_reached" in error_code or "rate_limit" in error_code.lower():
        raise RateLimitError(provider="codex")

    if status_code in (401, 403):
        raise AuthenticationError(provider="codex")

    retriable = status_code >= 500
    raise ProviderError(
        error_message,
        provider="codex",
        retriable=retriable,
        status_code=status_code,
    )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class CodexOAuthAdapter(ProviderAdapter):
    """Adapter for OpenAI models via the ChatGPT backend API (OAuth, subscription billing).

    Unlike the standard OpenAI adapter which uses API keys, this adapter
    authenticates via OAuth tokens from a ChatGPT Plus/Pro subscription.
    The backend endpoint and request format differ from the public OpenAI API:

    - Endpoint: ``https://chatgpt.com/backend-api/codex/responses``
    - Uses the Responses API format (``input`` instead of ``messages``)
    - Requires ``chatgpt-account-id`` header derived from the JWT
    """

    provider_name = "codex"

    def __init__(self, credentials: CodexCredentials | None = None) -> None:
        """Initialise the adapter.

        Args:
            credentials: Pre-existing OAuth credentials.  If ``None``, the
                adapter will attempt to load them from the CredentialManager
                at call time.
        """
        self._credentials = credentials
        self._refresh_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Credential management
    # ------------------------------------------------------------------

    def _get_credentials(self) -> CodexCredentials:
        """Return current credentials, loading from CredentialManager if needed.

        Checks oauth_token first (from browser OAuth flow), then falls back
        to api_key (legacy/manual entry).
        """
        if self._credentials is not None:
            return self._credentials

        try:
            from app.services.credential_manager import get_credential_manager

            cm = get_credential_manager()
            if cm.is_initialized:
                # Prefer OAuth token from browser flow
                token = cm.get("codex", "oauth_token") or cm.get_api_key("codex")
                refresh = cm.get("codex", "refresh_token")
                if token:
                    account_id = extract_account_id(token)
                    self._credentials = CodexCredentials(
                        access_token=token,
                        refresh_token=refresh,
                        account_id=account_id,
                    )
                    return self._credentials
        except Exception:
            logger.warning("Credential refresh failed", exc_info=True)

        raise AuthenticationError(provider="codex")

    async def _ensure_fresh_credentials(self) -> CodexCredentials:
        """Return credentials, refreshing the access token if expired.

        Uses an asyncio lock to prevent thundering herd within the process,
        and a file lock to coordinate across concurrent worker processes.
        If another process already refreshed, we read its cached token.
        """
        creds = self._get_credentials()

        if not creds.is_expired or not creds.refresh_token:
            return creds

        async with self._refresh_lock:
            # Re-check after acquiring — another coroutine may have refreshed
            creds = self._get_credentials()
            if not creds.is_expired:
                return creds

            logger.info("Codex access token expired, refreshing...")
            try:
                new_creds = await self._locked_refresh(creds.refresh_token)
                self._credentials = new_creds
                return new_creds
            except Exception:
                logger.warning("Codex token refresh failed, using existing token")
                return creds

    async def _locked_refresh(self, refresh_token: str) -> CodexCredentials:
        """Refresh the token using a file lock for cross-process safety.

        If another worker already refreshed (token cache file is fresh),
        reads the cached token instead of hitting the auth server again.

        The file lock is acquired/released in a thread via asyncio.to_thread()
        so the event loop is never blocked by the blocking FileLock.
        """
        def _read_cache_under_lock() -> CodexCredentials | None:
            """Acquire file lock and check for a recent cached token.

            Returns a CodexCredentials if the cache is fresh, else None.
            """
            lock = FileLock(str(_TOKEN_LOCK_PATH), timeout=10)
            with lock:
                if _TOKEN_CACHE_PATH.exists():
                    try:
                        cached = json.loads(_TOKEN_CACHE_PATH.read_text())
                        cached_at = cached.get("refreshed_at", 0)
                        # If refreshed within the last 30 seconds, use cached
                        if time.time() - cached_at < 30:
                            account_id = extract_account_id(cached["access_token"])
                            return CodexCredentials(
                                access_token=cached["access_token"],
                                refresh_token=cached.get("refresh_token", refresh_token),
                                account_id=account_id,
                            )
                    except (json.JSONDecodeError, KeyError):
                        pass
            return None

        def _write_cache_under_lock(new_creds: CodexCredentials) -> None:
            """Acquire file lock and write refreshed token to cache with secure permissions."""
            lock = FileLock(str(_TOKEN_LOCK_PATH), timeout=10)
            with lock, contextlib.suppress(OSError):
                _secure_write(
                    _TOKEN_CACHE_PATH,
                    json.dumps({
                        "access_token": new_creds.access_token,
                        "refresh_token": new_creds.refresh_token,
                        "refreshed_at": time.time(),
                    }),
                )

        # Step 1: Check cache under file lock (in a thread, non-blocking)
        cached_creds = await asyncio.to_thread(_read_cache_under_lock)
        if cached_creds is not None:
            return cached_creds

        # Step 2: Do the async token refresh outside the file lock
        new_creds = await refresh_access_token(refresh_token)

        # Step 3: Write result to cache under file lock (in a thread, non-blocking)
        await asyncio.to_thread(_write_cache_under_lock, new_creds)

        return new_creds

    # ------------------------------------------------------------------
    # ProviderAdapter interface
    # ------------------------------------------------------------------

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
            return await self._complete_impl(messages, model, max_tokens, temperature, **kwargs)

        return await _do_complete()

    async def _complete_impl(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> CompletionResult:
        """Internal non-streaming completion (collects full streamed response)."""
        creds = await self._ensure_fresh_credentials()
        resolved_model = self._resolve_model(model)
        input_items, instructions = _convert_messages_to_input(messages)
        body = _build_request_body(
            input_items,
            resolved_model,
            instructions=instructions,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,  # Always stream, collect locally
            **kwargs,
        )
        headers = _build_headers(creds)

        content_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0
        finish_reason: str | None = None
        response_model = resolved_model

        try:
            async with (
                httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client,
                client.stream("POST", CODEX_API_URL, json=body, headers=headers) as response,
            ):
                if response.status_code != 200:
                    error_body = await response.aread()
                    _handle_error_response(response.status_code, error_body.decode("utf-8", errors="replace"))

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type", "")

                    if event_type == "error":
                        msg = event.get("message") or event.get("code") or json.dumps(event)
                        raise ProviderError(f"Codex error: {msg}", provider="codex", retriable=False)

                    if event_type == "response.failed":
                        msg = (event.get("response") or {}).get("error", {}).get("message", "Codex response failed")
                        raise ProviderError(msg, provider="codex", retriable=False)

                    if event_type == "response.output_text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            content_parts.append(delta)

                    elif event_type == "response.content_part.delta":
                        # Alternative delta path
                        delta = event.get("delta", "")
                        if isinstance(delta, str) and delta:
                            content_parts.append(delta)

                    elif event_type in ("response.completed", "response.done"):
                        resp_data = event.get("response", {})
                        usage = resp_data.get("usage", {})
                        input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)
                        status = resp_data.get("status", "completed")
                        response_model = resp_data.get("model", resolved_model)
                        if status == "completed":
                            finish_reason = "stop"
                        elif status == "incomplete":
                            finish_reason = "length"
                        else:
                            finish_reason = status

        except (httpx.HTTPStatusError, httpx.ReadError, httpx.ConnectError) as exc:
            logger.error("Codex HTTP error: %s", exc)
            raise ProviderError(str(exc), provider="codex", retriable=True) from exc

        return CompletionResult(
            content="".join(content_parts),
            model=response_model,
            provider="codex",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=finish_reason,
        )

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
        resolved_model = self._resolve_model(model)
        input_items, instructions = _convert_messages_to_input(messages)
        body = _build_request_body(
            input_items,
            resolved_model,
            instructions=instructions,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )
        headers = _build_headers(creds)

        input_tokens = 0
        output_tokens = 0
        finish_reason: str | None = None

        try:
            async with (
                httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client,
                client.stream("POST", CODEX_API_URL, json=body, headers=headers) as response,
            ):
                if response.status_code != 200:
                    error_body = await response.aread()
                    _handle_error_response(response.status_code, error_body.decode("utf-8", errors="replace"))

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type", "")

                    if event_type == "error":
                        msg = event.get("message") or event.get("code") or json.dumps(event)
                        yield StreamEvent(type="error", error=f"Codex error: {msg}")
                        return

                    if event_type == "response.failed":
                        msg = (event.get("response") or {}).get("error", {}).get("message", "Codex response failed")
                        yield StreamEvent(type="error", error=msg)
                        return

                    if event_type == "response.output_text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            yield StreamEvent(type="content", content=delta)

                    elif event_type == "response.content_part.delta":
                        delta = event.get("delta", "")
                        if isinstance(delta, str) and delta:
                            yield StreamEvent(type="content", content=delta)

                    elif event_type in ("response.completed", "response.done"):
                        resp_data = event.get("response", {})
                        usage = resp_data.get("usage", {})
                        input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)
                        status = resp_data.get("status", "completed")
                        if status == "completed":
                            finish_reason = "stop"
                        elif status == "incomplete":
                            finish_reason = "length"
                        else:
                            finish_reason = status

        except (httpx.HTTPStatusError, httpx.ReadError, httpx.ConnectError) as exc:
            logger.error("Codex stream HTTP error: %s", exc)
            yield StreamEvent(type="error", error=str(exc))
            return

        yield StreamEvent(
            type="done",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=finish_reason,
        )

    async def health_check(self) -> bool:
        """Check if we can reach the Codex backend with current credentials."""
        try:
            creds = await self._ensure_fresh_credentials()
            headers = _build_headers(creds)
            # Send a minimal request; we expect a response (even an error is OK
            # as long as the server is reachable and auth works).
            body = {
                "model": "gpt-5.3-codex",
                "input": [{"role": "user", "content": "ping"}],
                "stream": False,
                "store": False,
                "max_output_tokens": 1,
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(CODEX_API_URL, json=body, headers=headers)
            return resp.status_code in (200, 400)  # 400 = bad request but reachable
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_model(model: str) -> str:
        """Strip the ``codex/`` prefix if present."""
        if model.startswith("codex/"):
            return model[len("codex/"):]
        return model
