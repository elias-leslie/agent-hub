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


class GeminiImageAdapter(ImageAdapter):
    """Adapter for Gemini image generation."""

    def __init__(self, api_key: str | None = None):
        """Initialize Gemini image adapter.

        Args:
            api_key: Google API key. Falls back to settings if not provided.
        """
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

        Args:
            prompt: Text description of desired image.
            model: Model identifier for image generation.
            size: Image dimensions (e.g., "1024x1024").
            style: Optional style hint to prepend to prompt.
            **kwargs: Additional parameters (ignored for now).

        Returns:
            ImageGenerationResult with PNG image data.

        Raises:
            ProviderError: If generation fails.
            RateLimitError: If rate limited.
            AuthenticationError: If auth fails.
        """
        # Enhance prompt with style if provided
        full_prompt = prompt
        if style:
            full_prompt = f"{style} style: {prompt}"

        try:
            # Use Gemini's image generation capability
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )

            # Extract image from response
            if not response.candidates:
                raise ProviderError(
                    "No image generated",
                    provider="gemini",
                    status_code=500,
                )

            # Find image part in response
            for candidate in response.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.inline_data and part.inline_data.data:
                            return ImageGenerationResult(
                                image_data=part.inline_data.data,
                                mime_type=part.inline_data.mime_type or "image/png",
                                model=model,
                                provider="gemini",
                                metadata={
                                    "size": size,
                                    "style": style,
                                    "prompt": prompt,
                                },
                            )

            raise ProviderError(
                "Response did not contain image data",
                provider="gemini",
                status_code=500,
            )

        except ValueError as e:
            raise AuthenticationError("gemini") from e
        except Exception as e:
            error_msg = str(e).lower()
            if "rate limit" in error_msg or "quota" in error_msg:
                raise RateLimitError("gemini") from e
            elif "authentication" in error_msg or "api key" in error_msg:
                raise AuthenticationError("gemini") from e
            else:
                raise ProviderError(
                    str(e),
                    provider="gemini",
                    status_code=500,
                    retriable=True,
                ) from e
