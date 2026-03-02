"""NVIDIA NIM image generation adapter.

Uses the NVIDIA GenAI endpoint (ai.api.nvidia.com/v1/genai/) which is separate
from the OpenAI-compatible chat endpoint used by NvidiaAdapter.

Supported models and their NVIDIA vendor-namespaced IDs:
  nvidia/flux.1-dev          → black-forest-labs/flux.1-dev
  nvidia/flux.1-schnell      → black-forest-labs/flux_1-schnell
  nvidia/stable-diffusion-3.5-large → stabilityai/stable-diffusion-3.5-large

On rate-limit, automatically walks down the fallback chain.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.adapters.base import AuthenticationError, ProviderError, RateLimitError
from app.adapters.image_base import ImageAdapter, ImageGenerationResult
from app.config import settings
from app.constants.models import NVIDIA_FLUX_1_DEV, NVIDIA_FLUX_1_SCHNELL, NVIDIA_SD_3_5_LARGE

logger = logging.getLogger(__name__)

_BASE_URL = "https://ai.api.nvidia.com/v1/genai"

# Maps our nvidia/<short> IDs to NVIDIA's vendor-namespaced path segments.
_MODEL_PATH: dict[str, str] = {
    "flux.1-dev": "black-forest-labs/flux.1-dev",
    "flux.1-schnell": "black-forest-labs/flux_1-schnell",
    "stable-diffusion-3.5-large": "stabilityai/stable-diffusion-3.5-large",
}

# Ordered best quality → fastest.  On rate-limit we walk down.
_FALLBACK_CHAIN = [NVIDIA_FLUX_1_DEV, NVIDIA_FLUX_1_SCHNELL, NVIDIA_SD_3_5_LARGE]


def _model_path(model: str) -> str:
    short = model.removeprefix("nvidia/")
    return _MODEL_PATH.get(short, short)


def _build_payload(model: str, prompt: str, width: int, height: int) -> dict[str, Any]:
    """Build the model-specific request payload."""
    short = model.removeprefix("nvidia/")
    if short == "flux.1-schnell":
        return {"prompt": prompt, "seed": 0, "steps": 4}
    return {
        "prompt": prompt,
        "mode": "base",
        "width": width,
        "height": height,
        "cfg_scale": 5,
        "steps": 50,
        "seed": 0,
    }


def _parse_size(size: str) -> tuple[int, int]:
    """Parse '1024x1024' → (1024, 1024), clamped to NVIDIA's valid range."""
    try:
        w, h = (int(x) for x in size.lower().split("x"))
        # NVIDIA accepts 768-1344 in multiples of 64; snap to nearest valid value
        w = max(768, min(1344, (w // 64) * 64))
        h = max(768, min(1344, (h // 64) * 64))
        return w, h
    except (ValueError, AttributeError):
        return 1024, 1024


def _map_error(status: int, body: str, model: str) -> None:
    """Raise the appropriate adapter error for a non-2xx response."""
    if status == 401:
        raise AuthenticationError("nvidia")
    if status == 429:
        raise RateLimitError("nvidia")
    raise ProviderError(
        f"NVIDIA image gen failed ({status}): {body[:200]}",
        provider="nvidia",
        status_code=status,
        retriable=status >= 500,
    )


class NvidiaImageAdapter(ImageAdapter):
    """Image generation adapter using NVIDIA NIM GenAI endpoint."""

    @property
    def provider_name(self) -> str:
        return "nvidia"

    def _api_key(self) -> str:
        key = settings.nvidia_api_key
        if not key:
            raise AuthenticationError("nvidia")
        return key

    async def generate_image(
        self,
        prompt: str,
        model: str = NVIDIA_FLUX_1_DEV,
        size: str = "1024x1024",
        style: str | None = None,
        **kwargs: Any,
    ) -> ImageGenerationResult:
        """Generate an image, falling back through models on rate-limit."""
        full_prompt = f"{style} style: {prompt}" if style else prompt
        width, height = _parse_size(size)
        api_key = self._api_key()

        models = [model] + [m for m in _FALLBACK_CHAIN if m != model]
        last_exc: Exception | None = None

        for try_model in models:
            try:
                result = await self._call_api(full_prompt, try_model, width, height, api_key)
                if try_model != model:
                    logger.info("NVIDIA image gen fell back %s → %s", model, try_model)
                return result
            except RateLimitError as exc:
                logger.warning("NVIDIA rate-limited on %s, trying next model", try_model)
                last_exc = exc
                continue
            except (AuthenticationError, ProviderError):
                raise

        raise last_exc  # type: ignore[misc]

    async def _call_api(
        self, prompt: str, model: str, width: int, height: int, api_key: str,
    ) -> ImageGenerationResult:
        url = f"{_BASE_URL}/{_model_path(model)}"
        payload = _build_payload(model, prompt, width, height)
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        if not resp.is_success:
            _map_error(resp.status_code, resp.text, model)

        data = resp.json()
        artifacts = data.get("artifacts", [])
        if not artifacts:
            raise ProviderError("No image in response", provider="nvidia", status_code=500)

        artifact = artifacts[0]
        if artifact.get("finishReason") not in ("SUCCESS", None):
            raise ProviderError(
                f"Generation failed: {artifact.get('finishReason')}",
                provider="nvidia", status_code=500,
            )

        image_bytes = base64.b64decode(artifact["base64"])
        return ImageGenerationResult(
            image_data=image_bytes,
            mime_type="image/jpeg",
            model=model,
            provider="nvidia",
            metadata={"size": f"{width}x{height}", "seed": artifact.get("seed")},
        )
