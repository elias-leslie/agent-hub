"""NVIDIA NIM image generation adapter.

Uses the NVIDIA GenAI endpoint (ai.api.nvidia.com/v1/genai/) which is separate
from the OpenAI-compatible chat endpoint used by NvidiaAdapter.

Vendor-namespaced paths (e.g. black-forest-labs/flux.1-dev) come from the
catalog ``upstream_id``. Kontext models need a reference image. Model fallback
is the caller's job: ``api/image.py`` walks the image agent's catalog chain.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.adapters.image_base import ImageAdapter, ImageGenerationResult
from app.llm.model_resolver import upstream_model_id
from app.services.llm_errors import AuthenticationError, ProviderError, RateLimitError
from app.services.provider_credentials import resolve_api_key

logger = logging.getLogger(__name__)

_BASE_URL = "https://ai.api.nvidia.com/v1/genai"

def _model_path(model: str) -> str:
    return upstream_model_id(model, "nvidia")


def _is_kontext(model: str) -> bool:
    return "kontext" in _model_path(model)


def _build_payload(
    model: str, prompt: str, width: int, height: int,
    reference_image_b64: str | None = None,
) -> dict[str, Any]:
    """Build the model-specific request payload."""
    # Kontext model: purpose-built for image editing with reference
    if _is_kontext(model):
        if not reference_image_b64:
            raise ProviderError(
                "FLUX.1-Kontext requires a reference_image",
                provider="nvidia",
                status_code=400,
            )
        return {
            "prompt": prompt,
            "image": reference_image_b64,
            "aspect_ratio": "match_input_image",
            "steps": 30,
            "cfg_scale": 3.5,
            "seed": 0,
        }

    # Standard models (flux.1-dev): use canny mode when reference provided
    payload = {
        "prompt": prompt,
        "mode": "canny" if reference_image_b64 else "base",
        "width": width,
        "height": height,
        "cfg_scale": 5,
        "steps": 50,
        "seed": 0,
    }
    if reference_image_b64:
        payload["image"] = reference_image_b64
        payload["preprocess_image"] = True
    return payload


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
        key = resolve_api_key("nvidia", None)
        if not key:
            raise AuthenticationError("nvidia")
        return key

    async def generate_image(
        self,
        prompt: str,
        model: str,
        size: str = "1024x1024",
        style: str | None = None,
        reference_image: bytes | None = None,
        reference_mime_type: str = "image/png",
        **kwargs: Any,
    ) -> ImageGenerationResult:
        """Generate an image with exactly ``model``."""
        full_prompt = f"{style} style: {prompt}" if style else prompt
        width, height = _parse_size(size)

        # Kontext expects raw base64; img2img models expect a data URI.
        ref_b64: str | None = None
        if reference_image:
            encoded = base64.b64encode(reference_image).decode()
            ref_b64 = encoded if _is_kontext(model) else f"data:{reference_mime_type};base64,{encoded}"

        return await self._call_api(full_prompt, model, width, height, self._api_key(), ref_b64)

    async def _call_api(
        self, prompt: str, model: str, width: int, height: int, api_key: str,
        reference_image_b64: str | None = None,
    ) -> ImageGenerationResult:
        url = f"{_BASE_URL}/{_model_path(model)}"
        payload = _build_payload(model, prompt, width, height, reference_image_b64)
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
