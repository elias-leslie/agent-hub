"""Cloudflare Workers AI image generation adapter.

Uses the custom REST endpoint at:
  https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/{model}

Response format: JSON ``{"result": {"image": "<base64-string>"}}``

FLUX.2 [klein] 9B supports reference images via multipart form data with
``input_image_0`` through ``input_image_3`` (up to 4 images, 512x512 each).

Model fallback is the caller's job: ``api/image.py`` walks the image agent's
catalog chain. Upstream ``@cf/`` paths come from the catalog ``upstream_id``.

FLUX.2-dev is not used: Workers AI returns HTTP 500 for it on our account
(verified 2026-10-09) while the same multipart request to klein succeeds.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.adapters.image_base import ImageAdapter, ImageGenerationResult
from app.llm.model_resolver import upstream_model_id
from app.services.llm_errors import AuthenticationError, ProviderError, RateLimitError
from app.services.provider_credentials import resolve_api_key, resolve_cloudflare_account_id

logger = logging.getLogger(__name__)

def _model_path(model: str) -> str:
    return upstream_model_id(model, "cloudflare")


def _is_flux_2(path: str) -> bool:
    """FLUX.2 models take multipart form data."""
    return "/flux-2-" in path


def _supports_sd_img2img(path: str) -> bool:
    """Stable Diffusion-family models accept a base64 image plus strength."""
    return "stable-diffusion" in path or "dreamshaper" in path



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
        model: str,
        size: str = "1024x1024",
        style: str | None = None,
        reference_image: bytes | None = None,
        reference_mime_type: str = "image/png",
        **kwargs: Any,
    ) -> ImageGenerationResult:
        """Generate an image with exactly ``model``."""
        full_prompt = f"{style} style: {prompt}" if style else prompt
        return await self._call_api(
            full_prompt, model, resolve_cloudflare_account_id(), self._api_key(),
            reference_image, reference_mime_type,
        )

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

        if _is_flux_2(path):
            resp = await self._call_multipart(url, headers, prompt, reference_image, reference_mime_type)
        else:
            payload: dict[str, Any] = {"prompt": prompt}
            if reference_image and _supports_sd_img2img(path):
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
