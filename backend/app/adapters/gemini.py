"""Gemini adapter using Google GenAI SDK (API key) or CloudCode PA (OAuth)."""

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from google import genai
from google.genai import types
from google.genai.types import HttpOptions

from app.adapters.base import CompletionResult, Message, ProviderAdapter, StreamEvent
from app.adapters.gemini_cloudcode import (
    CloudCodeClient,
    cloudcode_complete,
    cloudcode_stream,
    cloudcode_tool_loop,
)
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
_vertex_project: str = ""  # GCP project ID for CloudCode OAuth mode


def set_gemini_auth_preference(preference: str) -> None:
    """Set the Gemini auth preference (called by the preferences API)."""
    global _auth_preference
    if preference in ("oauth", "api_key"):
        _auth_preference = preference


def get_gemini_auth_preference() -> str:
    """Get the current Gemini auth preference."""
    return _auth_preference


def set_gemini_vertex_project(project: str) -> None:
    """Set the GCP project ID for CloudCode OAuth mode."""
    global _vertex_project
    _vertex_project = project


def get_gemini_vertex_project() -> str:
    """Get the GCP project ID for CloudCode OAuth mode."""
    return _vertex_project


def _resolve_oauth_data() -> dict[str, Any] | None:
    """Extract raw OAuth token data from DB credential manager.

    Returns a dict with access_token, refresh_token, project_id, expires_at
    or None if unavailable.
    """
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
        # Use the DB preference for project, not the token blob
        project_id = get_gemini_vertex_project() or data.get("project_id")

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "project_id": project_id,
            "expires_at": data.get("expires_at"),
        }
    except Exception:
        logger.debug("Failed to resolve Gemini OAuth data", exc_info=True)
        return None


class GeminiAdapter(ProviderAdapter):
    """Adapter for Gemini models.

    - API key / ADC mode: Uses the Google GenAI SDK (``genai.Client``).
    - OAuth mode: Uses raw HTTP to ``cloudcode-pa.googleapis.com`` via
      :class:`CloudCodeClient` — the same endpoint the Gemini CLI uses,
      which routes through a consumer subscription (zero per-token cost).
    """

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
        oauth_data = _resolve_oauth_data()
        preference = get_gemini_auth_preference()

        oauth_usable = bool(
            oauth_data
            and oauth_data.get("access_token")
            and oauth_data.get("project_id")
        )
        if oauth_data and oauth_data.get("access_token") and not oauth_data.get("project_id"):
            logger.warning(
                "Gemini OAuth credentials found but project_id is missing — "
                "falling back to API key. Re-run the OAuth flow to fix."
            )

        # ---- SDK client (api_key / ADC) — only created when needed ----
        self._client: genai.Client | None = None
        # ---- CloudCode client (OAuth) — only created when needed ----
        self._cc_client: CloudCodeClient | None = None

        if preference == "oauth" and oauth_usable:
            self._cc_client = self._make_cloudcode_client(oauth_data)
            self._auth_mode = "oauth"
        elif resolved_key:
            self._client = genai.Client(
                api_key=resolved_key,
                http_options=HttpOptions(timeout=300_000),
            )
            self._auth_mode = "api_key"
        elif oauth_usable:
            self._cc_client = self._make_cloudcode_client(oauth_data)
            self._auth_mode = "oauth"
        else:
            self._client = genai.Client(
                http_options=HttpOptions(timeout=300_000),
            )
            self._auth_mode = "adc"

        self._last_api_key = resolved_key
        self._oauth_project = oauth_data.get("project_id") if oauth_data else None
        logger.info(
            "Gemini adapter initialized with %s auth (preference=%s)",
            self._auth_mode,
            preference,
        )
        self._after_tool_callback = after_tool_callback

    @staticmethod
    def _make_cloudcode_client(oauth_data: dict[str, Any]) -> CloudCodeClient:
        """Create a CloudCodeClient from resolved OAuth data."""
        return CloudCodeClient(
            access_token=oauth_data["access_token"],
            refresh_token=oauth_data.get("refresh_token"),
            project_id=oauth_data["project_id"],
            expires_at=oauth_data.get("expires_at"),
        )

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _refresh_credentials(self) -> None:
        """Re-check CredentialManager for rotated credentials."""
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
            # Update CloudCodeClient if credential manager has newer data.
            # CloudCodeClient also handles its own token refresh internally.
            oauth_data = _resolve_oauth_data()
            if oauth_data and oauth_data.get("access_token") and oauth_data.get("project_id"):
                if self._cc_client is not None:
                    self._cc_client.access_token = oauth_data["access_token"]
                    self._cc_client.project_id = oauth_data["project_id"]
                    if oauth_data.get("refresh_token"):
                        self._cc_client.refresh_token = oauth_data["refresh_token"]
                    if oauth_data.get("expires_at"):
                        self._cc_client.expires_at = oauth_data["expires_at"]
                else:
                    self._cc_client = self._make_cloudcode_client(oauth_data)

    # ----- complete -------------------------------------------------------

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
        self._refresh_credentials()

        if self._auth_mode == "oauth" and self._cc_client is not None:
            return await cloudcode_complete(
                self._cc_client,
                messages,
                model,
                temperature,
                max_tokens,
                self.provider_name,
                kwargs,
            )

        from app.adapters.errors import with_retry

        @with_retry
        async def _do_complete() -> CompletionResult:
            return await do_complete_call(
                self._client, messages, model, temperature, max_tokens, self.provider_name, kwargs,
            )

        return await _do_complete()

    # ----- health_check ---------------------------------------------------

    async def health_check(self) -> bool:
        """Check if Gemini API is reachable."""
        try:
            from app.constants import GEMINI_FLASH

            if self._auth_mode == "oauth" and self._cc_client is not None:
                data = await self._cc_client.generate_content(
                    model=GEMINI_FLASH,
                    contents=[{"role": "user", "parts": [{"text": "hi"}]}],
                    generation_config={"maxOutputTokens": 50},
                )
                response = data.get("response", data)
                candidates = response.get("candidates", [])
                return bool(candidates)

            response = await self._client.aio.models.generate_content(  # type: ignore[union-attr]
                model=GEMINI_FLASH,
                contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
                config=types.GenerateContentConfig(max_output_tokens=50),
            )
            return response.text is not None or bool(response.candidates)
        except Exception as e:
            logger.warning("Gemini health check failed: %s", e)
            return False

    # ----- stream ---------------------------------------------------------

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

        if self._auth_mode == "oauth" and self._cc_client is not None:
            async for event in cloudcode_stream(
                self._cc_client,
                messages,
                model,
                temperature,
                max_tokens,
                self.provider_name,
                kwargs,
            ):
                yield event
            return

        # SDK path (api_key / ADC)
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
            async for chunk in await self._client.aio.models.generate_content_stream(  # type: ignore[union-attr]
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
            logger.error("Gemini stream error: %s", e)
            yield StreamEvent(type="error", error=str(e))

    # ----- complete_with_tools --------------------------------------------

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
        if self._auth_mode == "oauth" and self._cc_client is not None:
            self._refresh_credentials()
            async for event in cloudcode_tool_loop(
                client=self._cc_client,
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
            return

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
