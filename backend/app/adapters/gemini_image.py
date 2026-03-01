"""Gemini image generation adapter.

Supports both API key and OAuth authentication modes, mirroring the
text adapter's credential resolution chain.  OAuth mode uses
CloudCodeClient (same endpoint as Gemini CLI) for zero per-token cost.
"""

import base64
import logging
from typing import Any

from google.genai import types

from app.adapters.base import AuthenticationError, ProviderError, RateLimitError
from app.adapters.gemini_adapter_settings import (
    get_gemini_auth_preference,
    make_cloudcode_client,
    make_sdk_client,
    resolve_oauth_data,
)
from app.adapters.gemini_utils import resolve_api_key
from app.adapters.image_base import ImageAdapter, ImageGenerationResult
from app.config import settings
from app.constants import GEMINI_IMAGE

logger = logging.getLogger(__name__)


def _build_prompt(prompt: str, style: str | None) -> str:
    """Return prompt optionally prefixed with a style directive."""
    return f"{style} style: {prompt}" if style else prompt


def _extract_image_part(response: types.GenerateContentResponse) -> types.Part | None:
    """Return the first candidate part that contains inline image data, or None."""
    for candidate in response.candidates or []:
        if not (candidate.content and candidate.content.parts):
            continue
        for part in candidate.content.parts:
            if part.inline_data and part.inline_data.data:
                return part
    return None


def _build_result(
    part: types.Part, model: str, size: str, style: str | None, prompt: str
) -> ImageGenerationResult:
    """Construct an ImageGenerationResult from an inline-data part."""
    return ImageGenerationResult(
        image_data=part.inline_data.data,  # type: ignore[union-attr]
        mime_type=part.inline_data.mime_type or "image/png",  # type: ignore[union-attr]
        model=model,
        provider="gemini",
        metadata={"size": size, "style": style, "prompt": prompt},
    )


def _build_result_from_cloudcode(
    response: dict[str, Any], model: str, size: str, style: str | None, prompt: str,
) -> ImageGenerationResult:
    """Extract image data from a raw CloudCode JSON response."""
    for candidate in response.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline = part.get("inlineData", {})
            data = inline.get("data")
            if data:
                return ImageGenerationResult(
                    image_data=base64.b64decode(data),
                    mime_type=inline.get("mimeType", "image/png"),
                    model=model,
                    provider="gemini",
                    metadata={"size": size, "style": style, "prompt": prompt},
                )
    raise ProviderError("Response did not contain image data", provider="gemini", status_code=500)


def _map_exception(exc: Exception) -> None:
    """Re-raise *exc* as the appropriate adapter error type."""
    if isinstance(exc, ValueError):
        raise AuthenticationError("gemini") from exc
    error_msg = str(exc).lower()
    if "rate limit" in error_msg or "quota" in error_msg:
        raise RateLimitError("gemini") from exc
    if "authentication" in error_msg or "api key" in error_msg:
        raise AuthenticationError("gemini") from exc
    raise ProviderError(str(exc), provider="gemini", status_code=500, retriable=True) from exc


class GeminiImageAdapter(ImageAdapter):
    """Adapter for Gemini image generation.

    Auth modes (same resolution as the text adapter):
    - **OAuth**: CloudCodeClient → cloudcode-pa.googleapis.com (zero cost)
    - **API key**: genai.Client → generativelanguage.googleapis.com
    - **ADC**: genai.Client with Application Default Credentials
    """

    def __init__(self, api_key: str | None = None) -> None:
        resolved_key = resolve_api_key(api_key) or settings.gemini_api_key
        oauth_data = resolve_oauth_data()
        self._auth_mode, self._sdk_client, self._cc_client = (
            _pick_image_auth(resolved_key, oauth_data, get_gemini_auth_preference())
        )
        self._last_api_key = resolved_key
        # SDK client needed as fallback when CloudCode 404s on image models
        if self._auth_mode == "oauth" and resolved_key:
            self._sdk_client = make_sdk_client(resolved_key)
        logger.info(
            "Gemini image adapter initialized with %s auth (preference=%s)",
            self._auth_mode, get_gemini_auth_preference(),
        )

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _refresh_credentials(self) -> None:
        """Re-check CredentialManager for rotated credentials."""
        try:
            if self._auth_mode == "oauth" and self._cc_client is not None:
                oauth_data = resolve_oauth_data()
                if oauth_data and oauth_data.get("access_token"):
                    self._cc_client.access_token = oauth_data["access_token"]
                    if oauth_data.get("project_id"):
                        self._cc_client.project_id = oauth_data["project_id"]
                    if oauth_data.get("refresh_token"):
                        self._cc_client.refresh_token = oauth_data["refresh_token"]
                    if oauth_data.get("expires_at"):
                        self._cc_client.expires_at = oauth_data["expires_at"]
            elif self._auth_mode == "api_key":
                fresh = resolve_api_key(None) or settings.gemini_api_key
                if fresh and fresh != self._last_api_key:
                    self._sdk_client = make_sdk_client(fresh)
                    self._last_api_key = fresh
        except Exception:
            pass

    async def generate_image(
        self,
        prompt: str,
        model: str = GEMINI_IMAGE,
        size: str = "1024x1024",
        style: str | None = None,
        **kwargs: Any,
    ) -> ImageGenerationResult:
        """Generate an image using Gemini."""
        self._refresh_credentials()
        full_prompt = _build_prompt(prompt, style)

        try:
            if self._auth_mode == "oauth" and self._cc_client is not None:
                return await self._generate_via_cloudcode(full_prompt, model, size, style)
            return await self._generate_via_sdk(full_prompt, model, size, style)
        except (ProviderError, RateLimitError, AuthenticationError):
            raise
        except Exception as exc:
            _map_exception(exc)
            raise  # unreachable; satisfies type-checker

    async def _generate_via_sdk(
        self, prompt: str, model: str, size: str, style: str | None,
    ) -> ImageGenerationResult:
        """Generate image using the GenAI SDK (API key / ADC)."""
        response = await self._sdk_client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
        )
        if not response.candidates:
            raise ProviderError("No image generated", provider="gemini", status_code=500)
        part = _extract_image_part(response)
        if part is None:
            raise ProviderError(
                "Response did not contain image data", provider="gemini", status_code=500,
            )
        return _build_result(part, model, size, style, prompt)

    async def _generate_via_cloudcode(
        self, prompt: str, model: str, size: str, style: str | None,
    ) -> ImageGenerationResult:
        """Generate image using CloudCode PA (OAuth, zero cost)."""
        response = await self._cc_client.generate_content(
            model=model,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config={"responseModalities": ["IMAGE", "TEXT"]},
        )
        return _build_result_from_cloudcode(response, model, size, style, prompt)


def _pick_image_auth(
    resolved_key: str | None,
    oauth_data: dict[str, Any] | None,
    preference: str,
) -> tuple[str, Any, Any]:
    """Select auth mode for image generation.

    Returns (auth_mode, sdk_client_or_None, cloudcode_client_or_None).
    Same logic as the text adapter's pick_auth_mode.
    """
    oauth_usable = bool(
        oauth_data
        and oauth_data.get("access_token")
        and oauth_data.get("project_id")
    )

    if preference == "oauth" and oauth_usable:
        return "oauth", None, make_cloudcode_client(oauth_data)  # type: ignore[arg-type]
    if resolved_key:
        return "api_key", make_sdk_client(resolved_key), None
    if oauth_usable:
        return "oauth", None, make_cloudcode_client(oauth_data)  # type: ignore[arg-type]
    return "adc", make_sdk_client(), None
