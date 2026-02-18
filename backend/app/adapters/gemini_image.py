"""Gemini image generation adapter."""

import logging
from typing import Any

from google import genai
from google.genai import types

from app.adapters.base import AuthenticationError, ProviderError, RateLimitError
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
    """Adapter for Gemini image generation."""

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize Gemini image adapter.

        Resolution chain: explicit key → DB credential → env-var fallback.
        """
        if not api_key:
            from app.services.credential_manager import get_credential_manager

            cm = get_credential_manager()
            if cm.is_initialized:
                api_key = cm.get_api_key("gemini")

        self._api_key = api_key or settings.gemini_api_key
        if not self._api_key:
            raise ValueError("Google API key not configured")
        self._client = genai.Client(api_key=self._api_key)

    @property
    def provider_name(self) -> str:
        return "gemini"

    async def generate_image(
        self,
        prompt: str,
        model: str = GEMINI_IMAGE,
        size: str = "1024x1024",
        style: str | None = None,
        **kwargs: Any,
    ) -> ImageGenerationResult:
        """Generate an image using Gemini.

        Raises:
            ProviderError: If generation fails or response contains no image.
            RateLimitError: If the API reports rate limiting or quota exhaustion.
            AuthenticationError: If the API key is invalid.
        """
        full_prompt = _build_prompt(prompt, style)
        try:
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=full_prompt,
                config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
            )
            if not response.candidates:
                raise ProviderError("No image generated", provider="gemini", status_code=500)
            part = _extract_image_part(response)
            if part is None:
                raise ProviderError(
                    "Response did not contain image data", provider="gemini", status_code=500
                )
            return _build_result(part, model, size, style, prompt)
        except (ProviderError, RateLimitError, AuthenticationError):
            raise
        except Exception as exc:
            _map_exception(exc)
            raise  # unreachable; satisfies type-checker
