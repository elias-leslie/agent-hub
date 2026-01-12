"""Base interface for image generation adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ImageGenerationResult:
    """Result from image generation."""

    image_data: bytes  # Raw image bytes
    mime_type: str  # e.g., "image/png"
    model: str
    provider: str
    metadata: dict[str, Any] | None = None


class ImageAdapter(ABC):
    """Abstract base class for image generation adapters."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'gemini')."""
        ...

    @abstractmethod
    async def generate_image(
        self,
        prompt: str,
        model: str,
        size: str = "1024x1024",
        style: str | None = None,
        **kwargs: Any,
    ) -> ImageGenerationResult:
        """Generate an image from a text prompt.

        Args:
            prompt: Text description of desired image.
            model: Model identifier for image generation.
            size: Image dimensions (e.g., "1024x1024").
            style: Optional style hint (e.g., "photorealistic", "artistic").
            **kwargs: Additional provider-specific parameters.

        Returns:
            ImageGenerationResult with image data and metadata.

        Raises:
            ProviderError: If generation fails.
            RateLimitError: If rate limited.
            AuthenticationError: If auth fails.
        """
        ...
