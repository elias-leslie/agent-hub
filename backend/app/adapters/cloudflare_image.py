"""Cloudflare Workers AI image generation adapter.

Uses the custom REST endpoint at:
  https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/{model}

Response format: JSON ``{"result": {"image": "<base64-string>"}}``

FLUX.2-dev supports reference images via multipart form data with
``input_image_0`` through ``input_image_3`` (up to 4 images, 512x512 each).

On rate-limit, walks down a fallback chain:
  FLUX.2-dev → FLUX.1-schnell → SD XL Lightning
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.adapters.image_base import ImageAdapter, ImageGenerationResult
from app.constants.models import (
    CF_FLUX_1_SCHNELL,
    CF_FLUX_2_DEV,
    CF_SD_XL_LIGHTNING,
)
from app.services.llm_errors import AuthenticationError, ProviderError, RateLimitError
from app.services.provider_credentials import resolve_api_key, resolve_cloudflare_account_id

logger = logging.getLogger(__name__)

# Maps our cloudflare/<short> IDs to @cf/ model paths.
_MODEL_PATH: dict[str, str] = {
    "flux-2-dev": "@cf/black-forest-labs/flux-2-dev",
    "flux-1-schnell": "@cf/black-forest-labs/flux-1-schnell",
    "sd-xl-lightning": "@cf/bytedance/stable-diffusion-xl-lightning",
    "sd-xl-base": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    "sd-v1.5-img2img": "@cf/runwayml/stable-diffusion-v1-5-img2img",
    "dreamshaper-8-lcm": "@cf/lykon/dreamshaper-8-lcm",
    "leonardo-phoenix": "@cf/leonardo/phoenix-1.0",
    "leonardo-lucid-origin": "@cf/leonardo/lucid-origin",
}

# SD models that support img2img via base64 image + strength parameter
_SD_IMG2IMG_MODELS = {"sd-xl-lightning", "sd-xl-base", "sd-v1.5-img2img", "dreamshaper-8-lcm"}

# Ordered best quality → fastest. On rate-limit we walk down.
_FALLBACK_CHAIN = [CF_FLUX_2_DEV, CF_FLUX_1_SCHNELL, CF_SD_XL_LIGHTNING]



def _model_path(model: str) -> str:
    short = model.removeprefix("cloudflare/")
    return _MODEL_PATH.get(short, short)


def _map_error(status: int, body: str) -> None:
    """Raise the appropriate adapter error for a non-2xx response."""
    if status == 401:
        raise AuthenticationError("cloudflare")
    if status == 429:
        raise RateLimitError("cloudflare")
    raise ProviderError(
        f"Cloudflare image gen failed ({status}): {body[:200]}",
        provider="cloudflare",
        status_code=status,
        retriable=status >= 500,
    )


class CloudflareImageAdapter(ImageAdapter):
    """Image generation adapter using Cloudflare Workers AI."""

    @property
    def provider_name(self) -> str:
        return "cloudflare"

    def _api_key(self) -> str:
        key = resolve_api_key("cloudflare", None)
        if not key:
            raise AuthenticationError("cloudflare")
        return key

    async def generate_image(
        self,
        prompt: str,
        model: str = CF_FLUX_2_DEV,
        size: str = "1024x1024",
        style: str | None = None,
        reference_image: bytes | None = None,
        reference_mime_type: str = "image/png",
        **kwargs: Any,
    ) -> ImageGenerationResult:
        """Generate an image, falling back through models on rate-limit."""
        full_prompt = f"{style} style: {prompt}" if style else prompt
        api_key = self._api_key()
        account_id = resolve_cloudflare_account_id()

        models = [model] + [m for m in _FALLBACK_CHAIN if m != model]
        last_exc: Exception | None = None

        for try_model in models:
            try:
                result = await self._call_api(
                    full_prompt, try_model, account_id, api_key,
                    reference_image, reference_mime_type,
                )
                if try_model != model:
                    logger.info("Cloudflare image gen fell back %s → %s", model, try_model)
                return result
            except RateLimitError as exc:
                logger.warning("Cloudflare rate-limited on %s, trying next model", try_model)
                last_exc = exc
                continue
            except (AuthenticationError, ProviderError):
                raise

        raise last_exc  # type: ignore[misc]

    async def _call_api(
        self,
        prompt: str,
        model: str,
        account_id: str,
        api_key: str,
        reference_image: bytes | None = None,
        reference_mime_type: str = "image/png",
    ) -> ImageGenerationResult:
        path = _model_path(model)
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{path}"
        headers = {"Authorization": f"Bearer {api_key}"}

        # FLUX.2-dev always requires multipart form data
        short = model.removeprefix("cloudflare/")
        if short == "flux-2-dev":
            resp = await self._call_multipart(url, headers, prompt, reference_image, reference_mime_type)
        else:
            payload: dict[str, Any] = {"prompt": prompt}
            if reference_image and short in _SD_IMG2IMG_MODELS:
                payload["image_b64"] = base64.b64encode(reference_image).decode()
                payload["strength"] = 0.65
                payload["num_steps"] = 20
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    url,
                    headers={**headers, "Content-Type": "application/json"},
                    json=payload,
                )

        if not resp.is_success:
            _map_error(resp.status_code, resp.text)

        # Some CF models (SD XL Lightning) return raw image bytes; others return JSON.
        content_type = resp.headers.get("content-type", "")
        if content_type.startswith(("image/", "application/octet-stream")):
            image_bytes = resp.content
            mime = "image/jpeg" if resp.content[:2] == b"\xff\xd8" else "image/png"
        else:
            data = resp.json()
            result_data = data.get("result", data)
            image_b64 = result_data.get("image")
            if not image_b64:
                raise ProviderError("No image in response", provider="cloudflare", status_code=500)
            image_bytes = base64.b64decode(image_b64)
            mime = "image/jpeg" if image_bytes[:2] == b"\xff\xd8" else "image/png"

        return ImageGenerationResult(
            image_data=image_bytes,
            mime_type=mime,
            model=model,
            provider="cloudflare",
            metadata={"prompt": prompt},
        )

    async def _call_multipart(
        self,
        url: str,
        headers: dict[str, str],
        prompt: str,
        reference_image: bytes | None,
        reference_mime_type: str,
    ) -> httpx.Response:
        """Send FLUX.2-dev request via multipart form data, optionally with reference image."""
        files: dict[str, Any] = {
            "prompt": (None, prompt),
        }
        if reference_image:
            files["input_image_0"] = ("reference.png", reference_image, reference_mime_type)
        async with httpx.AsyncClient(timeout=120.0) as client:
            return await client.post(url, headers=headers, files=files)
