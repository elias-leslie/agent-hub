"""Gemini image generation adapter.

Uses API key auth against generativelanguage.googleapis.com.

On rate-limit, automatically falls back through the model chain:
  gemini-3-pro-image-preview → gemini-3.1-flash-image-preview → gemini-2.5-flash-image
"""

import logging
from typing import Any

from google import genai
from google.genai import types

from app.adapters.image_base import ImageAdapter, ImageGenerationResult
from app.constants import GEMINI_IMAGE, GEMINI_IMAGE_NANO, GEMINI_IMAGE_NANO2
from app.services.llm_errors import AuthenticationError, ProviderError, RateLimitError
from app.services.provider_credentials import resolve_api_key

logger = logging.getLogger(__name__)

# Ordered best → fastest.  On rate-limit we walk down the chain.
_MODEL_FALLBACK_CHAIN = [GEMINI_IMAGE, GEMINI_IMAGE_NANO2, GEMINI_IMAGE_NANO]


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
    """Gemini image generation via API key + model fallback on rate-limit."""

    def __init__(self, api_key: str | None = None) -> None:
        resolved_key = resolve_api_key("gemini", api_key)
        self._sdk_client = _make_image_client(resolved_key)
        self._last_api_key = resolved_key
        logger.info("Gemini image adapter initialized with api_key auth")

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _refresh_credentials(self) -> None:
        """Re-check CredentialManager for rotated API key."""
        try:
            fresh = resolve_api_key("gemini")
            if fresh != self._last_api_key:
                self._sdk_client = _make_image_client(fresh)
                self._last_api_key = fresh
        except Exception:
            logger.debug("Gemini image API key refresh failed", exc_info=True)

    async def generate_image(
        self,
        prompt: str,
        model: str = GEMINI_IMAGE,
        size: str = "1024x1024",
        style: str | None = None,
        reference_image: bytes | None = None,
        reference_mime_type: str = "image/png",
        **kwargs: Any,
    ) -> ImageGenerationResult:
        """Generate an image, falling back through models on rate-limit."""
        self._refresh_credentials()
        full_prompt = _build_prompt(prompt, style)

        # Build fallback chain starting with the requested model
        models = [model] + [m for m in _MODEL_FALLBACK_CHAIN if m != model]
        last_exc: Exception | None = None

        for try_model in models:
            try:
                result = await self._generate_via_sdk(
                    full_prompt, try_model, size, style, reference_image, reference_mime_type,
                )
                if try_model != model:
                    logger.info("Image gen fell back %s → %s", model, try_model)
                return result
            except RateLimitError as exc:
                logger.warning("Rate-limited on %s, trying next model", try_model)
                last_exc = exc
                continue
            except (ProviderError, AuthenticationError):
                raise
            except Exception as exc:
                # _map_exception re-raises; catch rate-limits so fallback continues
                try:
                    _map_exception(exc)
                except RateLimitError as mapped:
                    logger.warning("Rate-limited on %s, trying next model", try_model)
                    last_exc = mapped
                    continue
                except Exception:
                    raise

        # All models exhausted
        raise last_exc  # type: ignore[misc]

    async def _generate_via_sdk(
        self, prompt: str, model: str, size: str, style: str | None,
        reference_image: bytes | None = None, reference_mime_type: str = "image/png",
    ) -> ImageGenerationResult:
        """Generate image using the GenAI SDK (API key only)."""
        if self._sdk_client is None:
            raise ProviderError("Gemini API key is not configured", provider="gemini", retriable=False)

        # Build contents: if reference image provided, send as multimodal parts
        if reference_image:
            contents: list[types.Part] = [
                types.Part.from_bytes(data=reference_image, mime_type=reference_mime_type),
                types.Part.from_text(text=prompt),
            ]
        else:
            contents = prompt

        response = await self._sdk_client.aio.models.generate_content(
            model=model,
            contents=contents,
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


def _make_image_client(resolved_key: str | None) -> Any | None:
    """Create the SDK client used for Gemini image generation."""
    if resolved_key:
        return genai.Client(api_key=resolved_key)
    return None
