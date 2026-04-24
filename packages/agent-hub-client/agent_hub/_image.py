"""Image generation operations."""

from typing import Any

import httpx

from agent_hub.constants import DEFAULT_IMAGE_MODEL
from agent_hub._utils import handle_error
from agent_hub.models import ImageGenerationResponse


def generate_image_sync(
    client: httpx.Client,
    headers: dict[str, str],
    prompt: str,
    project_id: str,
    purpose: str | None = None,
    agent_slug: str | None = None,
    model: str = DEFAULT_IMAGE_MODEL,
    size: str = "1024x1024",
    style: str | None = None,
    reference_image: str | None = None,
    reference_mime_type: str | None = None,
) -> ImageGenerationResponse:
    """Generate an image from a text prompt (sync).

    Args:
        client: HTTP client.
        headers: Request headers.
        prompt: Text description of desired image.
        project_id: Project ID for session tracking.
        purpose: Purpose of this generation.
        model: Model identifier for image generation.
        size: Image dimensions.
        style: Style hint.

    Returns:
        ImageGenerationResponse with base64 image data.
    """
    payload: dict[str, Any] = {
        "prompt": prompt,
        "project_id": project_id,
        "model": model,
        "size": size,
    }
    if purpose:
        payload["purpose"] = purpose
    if agent_slug:
        payload["agent_slug"] = agent_slug
    if style:
        payload["style"] = style
    if reference_image:
        payload["reference_image"] = reference_image
    if reference_mime_type:
        payload["reference_mime_type"] = reference_mime_type

    response = client.post("/api/generate-image", json=payload, headers=headers)

    if not response.is_success:
        handle_error(response)

    return ImageGenerationResponse.model_validate(response.json())


async def generate_image_async(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    prompt: str,
    project_id: str,
    purpose: str | None = None,
    agent_slug: str | None = None,
    model: str = DEFAULT_IMAGE_MODEL,
    size: str = "1024x1024",
    style: str | None = None,
    reference_image: str | None = None,
    reference_mime_type: str | None = None,
) -> ImageGenerationResponse:
    """Generate an image from a text prompt (async).

    Args:
        client: Async HTTP client.
        headers: Request headers.
        prompt: Text description of desired image.
        project_id: Project ID for session tracking.
        purpose: Purpose of this generation.
        model: Model identifier for image generation.
        size: Image dimensions.
        style: Style hint.

    Returns:
        ImageGenerationResponse with base64 image data.
    """
    payload: dict[str, Any] = {
        "prompt": prompt,
        "project_id": project_id,
        "model": model,
        "size": size,
    }
    if purpose:
        payload["purpose"] = purpose
    if agent_slug:
        payload["agent_slug"] = agent_slug
    if style:
        payload["style"] = style
    if reference_image:
        payload["reference_image"] = reference_image
    if reference_mime_type:
        payload["reference_mime_type"] = reference_mime_type

    response = await client.post("/api/generate-image", json=payload, headers=headers)

    if not response.is_success:
        handle_error(response)

    return ImageGenerationResponse.model_validate(response.json())
