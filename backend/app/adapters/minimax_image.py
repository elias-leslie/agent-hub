"""MiniMax image generation adapter.

Uses the dedicated image endpoint (api.minimax.io/v1/image_generation) which
is separate from the OpenAI-compatible chat endpoint used by MinimaxAdapter.

Supported model:
  minimax/image-01 → API model "image-01"

MiniMax error codes in base_resp.status_code:
  0    success
  1002 rate limit exceeded
  1004 authentication failed
  1008 insufficient balance
  1026 sensitive content
  2013 invalid parameters
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.adapters.image_base import ImageAdapter, ImageGenerationResult
from app.constants.models import MINIMAX_IMAGE_01
from app.services.llm_errors import AuthenticationError, ProviderError, RateLimitError
from app.services.provider_credentials import resolve_api_key

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.minimax.io/v1/image_generation"

# MiniMax error code → exception mapping
_RATE_LIMIT_CODES = {1002}
_AUTH_CODES = {1004, 1008, 2049}
_CONTENT_CODES = {1026}

_SIZE_TO_ASPECT: dict[str, str] = {
    "1024x1024": "1:1",
    "1792x1024": "16:9",
    "1024x1792": "9:16",
    "1344x768": "16:9",
    "768x1344": "9:16",
}


def _aspect_ratio(size: str) -> str:
    """Map a WxH size string to the nearest MiniMax aspect ratio."""
    if size in _SIZE_TO_ASPECT:
        return _SIZE_TO_ASPECT[size]
    try:
        w, h = (int(x) for x in size.lower().split("x"))
        ratio = w / h
        if ratio > 1.5:
            return "16:9"
        if ratio < 0.67:
            return "9:16"
        return "1:1"
    except (ValueError, AttributeError, ZeroDivisionError):
        return "1:1"


def _check_status(base_resp: dict[str, Any]) -> None:
    """Raise the appropriate error for non-zero base_resp.status_code."""
    code = base_resp.get("status_code", 0)
    if code == 0:
        return
    msg = base_resp.get("status_msg", "unknown error")
    if code in _RATE_LIMIT_CODES:
        raise RateLimitError("minimax")
    if code in _AUTH_CODES:
        raise AuthenticationError("minimax")
    if code in _CONTENT_CODES:
        raise ProviderError(
            f"Content filtered by MiniMax: {msg}", provider="minimax", status_code=400,
        )
    raise ProviderError(
        f"MiniMax image gen error {code}: {msg}", provider="minimax", status_code=500, retriable=True,
    )


class MinimaxImageAdapter(ImageAdapter):
    """Image generation adapter using MiniMax image_generation endpoint."""

    @property
    def provider_name(self) -> str:
        return "minimax"

    def _api_key(self) -> str:
        key = resolve_api_key("minimax", None)
        if not key:
            raise AuthenticationError("minimax")
        if key.startswith("sk-cp-"):
            raise ProviderError(
                (
                    "MiniMax coding-plan API keys are not valid for image_generation. "
                    "Use a pay-as-you-go MiniMax API key from Account > API Keys."
                ),
                provider="minimax",
                status_code=400,
                retriable=False,
            )
        return key

    async def generate_image(
        self,
        prompt: str,
        model: str = MINIMAX_IMAGE_01,
        size: str = "1024x1024",
        style: str | None = None,
        reference_image: bytes | None = None,
        reference_mime_type: str = "image/png",
        **kwargs: Any,
    ) -> ImageGenerationResult:
        """Generate an image from a text prompt using MiniMax image-01.

        When reference_image is provided, uses MiniMax's subject_reference
        with type "character" (human face reference). Non-face references
        may not produce good results — this is a MiniMax API limitation.
        """
        full_prompt = f"{style} style: {prompt}" if style else prompt
        api_key = self._api_key()
        api_model = model.removeprefix("minimax/")
        aspect = _aspect_ratio(size)

        payload: dict[str, Any] = {
            "model": api_model,
            "prompt": full_prompt,
            "aspect_ratio": aspect,
            "response_format": "base64",
            "n": 1,
        }

        # Add subject_reference for character consistency when reference image provided
        if reference_image:
            mime = reference_mime_type.removeprefix("image/")
            b64 = base64.b64encode(reference_image).decode()
            payload["subject_reference"] = [{
                "type": "character",
                "image_file": f"data:image/{mime};base64,{b64}",
            }]

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                _ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )

        if resp.status_code == 401:
            raise AuthenticationError("minimax")
        if resp.status_code == 429:
            raise RateLimitError("minimax")
        if not resp.is_success:
            raise ProviderError(
                f"MiniMax image gen failed ({resp.status_code}): {resp.text[:200]}",
                provider="minimax", status_code=resp.status_code, retriable=resp.status_code >= 500,
            )

        data = resp.json()
        _check_status(data.get("base_resp", {}))

        images: list[str] = data.get("data", {}).get("image_base64", [])
        if not images:
            raise ProviderError(
                "No image data in MiniMax response", provider="minimax", status_code=500,
            )

        image_bytes = base64.b64decode(images[0])
        return ImageGenerationResult(
            image_data=image_bytes,
            mime_type="image/jpeg",
            model=model,
            provider="minimax",
            metadata={"aspect_ratio": aspect, "size": size},
        )
