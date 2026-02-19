"""Gemini adapter using Google GenAI SDK."""

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from google import genai
from google.genai import types
from google.genai.types import HttpOptions

from app.adapters.base import CompletionResult, Message, ProviderAdapter, StreamEvent
from app.adapters.gemini_thinking import get_thinking_level
from app.adapters.gemini_tools import execute_tool_loop
from app.adapters.gemini_utils import (
    build_stream_config,
    convert_messages,
    do_complete_call,
    extract_chunk_tool_events,
    resolve_api_key,
)
from app.config import settings

logger = logging.getLogger(__name__)


# Module-level auth preference cache. Updated by the preferences API
# when the user changes their preference. Checked at credential refresh time.
_auth_preference: str = "api_key"  # "oauth" or "api_key"


def set_gemini_auth_preference(preference: str) -> None:
    """Set the Gemini auth preference (called by the preferences API)."""
    global _auth_preference
    if preference in ("oauth", "api_key"):
        _auth_preference = preference


def get_gemini_auth_preference() -> str:
    """Get the current Gemini auth preference."""
    return _auth_preference


def _resolve_oauth_credentials() -> Any:
    """Try to build google.oauth2.credentials.Credentials from DB OAuth token."""
    try:
        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        if not cm.is_initialized:
            return None

        token_json = cm.get("gemini", "oauth_token")
        if not token_json:
            return None

        data = json.loads(token_json)
        access_token = data.get("access_token")
        if not access_token:
            return None

        refresh_token = cm.get("gemini", "refresh_token")

        from google.oauth2.credentials import Credentials

        from app.adapters.gemini_auth import (
            GEMINI_CLIENT_ID,
            GEMINI_CLIENT_SECRET,
            GEMINI_TOKEN_URL,
        )

        return Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri=GEMINI_TOKEN_URL,
            client_id=GEMINI_CLIENT_ID,
            client_secret=GEMINI_CLIENT_SECRET,
        )
    except Exception:
        logger.debug("Failed to resolve Gemini OAuth credentials", exc_info=True)
        return None


class GeminiAdapter(ProviderAdapter):
    """Adapter for Gemini models via Google GenAI API."""

    def __init__(
        self,
        api_key: str | None = None,
        after_tool_callback: (Callable[[str, dict[str, Any], str, int | None], Awaitable[None]] | None) = None,
    ):
        """Initialize Gemini adapter.

        Auth priority depends on the ``gemini_auth_preference`` setting:
        - ``"api_key"`` (default): API key > OAuth > ADC
        - ``"oauth"``: OAuth > API key > ADC
        """
        resolved_key = resolve_api_key(api_key) or settings.gemini_api_key
        oauth_creds = _resolve_oauth_credentials()
        preference = get_gemini_auth_preference()

        # SDK timeout is in milliseconds; 300_000 ms = 300 s for agentic calls
        if preference == "oauth" and oauth_creds:
            # User prefers OAuth and it's available
            self._client = genai.Client(
                credentials=oauth_creds,
                http_options=HttpOptions(timeout=300_000),
            )
            self._auth_mode = "oauth"
        elif resolved_key:
            # API key path (default preference or OAuth not available)
            self._client = genai.Client(
                api_key=resolved_key,
                http_options=HttpOptions(timeout=300_000),
            )
            self._auth_mode = "api_key"
        elif oauth_creds:
            # No API key, fall back to OAuth
            self._client = genai.Client(
                credentials=oauth_creds,
                http_options=HttpOptions(timeout=300_000),
            )
            self._auth_mode = "oauth"
        else:
            # ADC path — no API key or OAuth; SDK auto-discovers credentials
            self._client = genai.Client(
                http_options=HttpOptions(timeout=300_000),
            )
            self._auth_mode = "adc"
        self._last_api_key = resolved_key
        logger.info(f"Gemini adapter initialized with {self._auth_mode} auth (preference={preference})")
        self._after_tool_callback = after_tool_callback

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _refresh_credentials(self) -> None:
        """Re-check CredentialManager for rotated credentials.

        For api_key mode: checks if the key has changed.
        For oauth mode: rebuilds credentials from the cache (google-auth
        handles token refresh via the refresh_token automatically).
        ADC tokens are auto-refreshed by the Google auth library.
        """
        if self._auth_mode == "api_key":
            try:
                fresh = resolve_api_key(None) or settings.gemini_api_key
                if fresh and fresh != self._last_api_key:
                    self._client = genai.Client(
                        api_key=fresh,
                        http_options=HttpOptions(timeout=300_000),
                    )
                    self._last_api_key = fresh
                    logger.debug("Gemini: credential refreshed from cache")
            except Exception:
                pass
        elif self._auth_mode == "oauth":
            oauth_creds = _resolve_oauth_credentials()
            if oauth_creds:
                self._client = genai.Client(
                    credentials=oauth_creds,
                    http_options=HttpOptions(timeout=300_000),
                )

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        """Generate completion using Gemini API."""
        from app.adapters.errors import with_retry

        self._refresh_credentials()

        @with_retry
        async def _do_complete() -> CompletionResult:
            return await do_complete_call(
                self._client, messages, model, temperature, max_tokens, self.provider_name, kwargs,
            )

        return await _do_complete()

    async def health_check(self) -> bool:
        """Check if Gemini API is reachable."""
        try:
            from app.constants import GEMINI_FLASH

            response = await self._client.aio.models.generate_content(
                model=GEMINI_FLASH,
                contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
                config=types.GenerateContentConfig(max_output_tokens=50),
            )
            return response.text is not None or bool(response.candidates)
        except Exception as e:
            logger.warning(f"Gemini health check failed: {e}")
            return False

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream completion from Gemini API."""
        self._refresh_credentials()
        system_instruction, contents = convert_messages(messages)
        try:
            config = build_stream_config(
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                system_instruction=system_instruction,
                tools_defs=kwargs.get("tools"),
                thinking_level=get_thinking_level(model, kwargs.get("thinking_level")),
            )
            total_content = ""
            last_chunk = None
            async for chunk in await self._client.aio.models.generate_content_stream(
                model=model, contents=contents, config=config,
            ):
                last_chunk = chunk
                if chunk.text:
                    total_content += chunk.text
                    yield StreamEvent(type="content", content=chunk.text)
                for event in extract_chunk_tool_events(chunk):
                    yield event

            input_tokens = 0
            output_tokens = len(total_content) // 4
            if last_chunk and last_chunk.usage_metadata:
                input_tokens = last_chunk.usage_metadata.prompt_token_count or 0
                output_tokens = last_chunk.usage_metadata.candidates_token_count or 0

            yield StreamEvent(
                type="done",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason="STOP",
            )
        except Exception as e:
            logger.error(f"Gemini stream error: {e}")
            yield StreamEvent(type="error", error=str(e))

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
        """Run agentic loop with tool execution, yielding (event, session_id) tuples."""
        async for event in execute_tool_loop(
            client=self._client,
            messages=messages,
            model=model,
            tools=tools,
            working_dir=working_dir,
            max_tokens=max_tokens,
            max_turns=max_turns,
            provider_name=self.provider_name,
            project_id=project_id,
            **kwargs,
        ):
            yield event
