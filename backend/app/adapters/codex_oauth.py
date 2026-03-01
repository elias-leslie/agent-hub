"""Codex OAuth adapter -- ChatGPT subscription-based OpenAI access.

Uses the ChatGPT backend Responses API (``/backend-api/codex/responses``)
with OAuth bearer tokens from a ChatGPT Plus/Pro subscription.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

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
    refresh_access_token,
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


# ---------------------------------------------------------------------------
# Message conversion
# ---------------------------------------------------------------------------


def _convert_messages_to_input(messages: list[Message]) -> tuple[list[dict[str, Any]], str | None]:
    """Convert internal Message objects to Responses API ``input`` format.

    System messages become ``instructions`` at the top level, so they are
    filtered out and returned separately.
    """
    instructions: str | None = None
    input_items: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == "system":
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            instructions = f"{instructions}\n{text}" if instructions else text
            continue
        input_items.append({"role": msg.role, "content": msg.content})

    return input_items, instructions


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
        self._credentials = credentials
        self._refresh_lock = asyncio.Lock()
        # Eagerly verify credentials exist so the registry/prober can skip
        # this provider when unconfigured, rather than deferring to health_check.
        if credentials is None:
            self._get_credentials()

    # ------------------------------------------------------------------
    # Credential management
    # ------------------------------------------------------------------

    def _get_credentials(self) -> CodexCredentials:
        """Return current credentials, loading from CredentialManager if needed."""
        if self._credentials is not None:
            return self._credentials

        try:
            from app.services.credential_manager import get_credential_manager

            cm = get_credential_manager()
            if cm.is_initialized:
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
        """
        creds = self._get_credentials()
        if not creds.is_expired or not creds.refresh_token:
            return creds

        async with self._refresh_lock:
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

        Checks the cache first (in a thread to avoid blocking the event loop),
        refreshes if needed, then writes the result to cache.
        """
        cached = await asyncio.to_thread(read_cached_token, refresh_token)
        if cached is not None:
            return cached

        new_creds = await refresh_access_token(refresh_token)
        await asyncio.to_thread(write_cached_token, new_creds)
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

        try:
            async with (
                httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client,
                client.stream("POST", CODEX_API_URL, json=body, headers=headers) as response,
            ):
                if response.status_code != 200:
                    error_body = await response.aread()
                    handle_error_response(
                        response.status_code, error_body.decode("utf-8", errors="replace")
                    )
                return await collect_completion(response, resolved_model)
        except (httpx.HTTPStatusError, httpx.ReadError, httpx.ConnectError) as exc:
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
        resolved_model = self._resolve_model(model)
        input_items, instructions = _convert_messages_to_input(messages)
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

        try:
            async with (
                httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client,
                client.stream("POST", CODEX_API_URL, json=body, headers=headers) as response,
            ):
                if response.status_code != 200:
                    error_body = await response.aread()
                    handle_error_response(
                        response.status_code, error_body.decode("utf-8", errors="replace")
                    )
                async for event in iter_stream_events(response):
                    yield event
        except (httpx.HTTPStatusError, httpx.ReadError, httpx.ConnectError) as exc:
            logger.error("Codex stream HTTP error: %s", exc)
            yield StreamEvent(type="error", error=str(exc))

    async def health_check(self) -> bool:
        """Check if we can reach the Codex backend with current credentials."""
        try:
            creds = await self._ensure_fresh_credentials()
            headers = build_headers(creds)
            body = {
                "model": "gpt-5.3-codex",
                "input": [{"role": "user", "content": "ping"}],
                "stream": False,
                "store": False,
                "max_output_tokens": 1,
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(CODEX_API_URL, json=body, headers=headers)
            return resp.status_code in (200, 400)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_model(model: str) -> str:
        """Strip the ``codex/`` prefix if present."""
        if model.startswith("codex/"):
            return model[len("codex/") :]
        return model
