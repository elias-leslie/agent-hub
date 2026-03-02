"""Image generation API endpoint.

Routes to the appropriate image adapter based on the model's provider prefix:
  gemini/*      → GeminiImageAdapter      (generativelanguage.googleapis.com)
  nvidia/*      → NvidiaImageAdapter      (ai.api.nvidia.com/v1/genai/)
  minimax/*     → MinimaxImageAdapter     (api.minimax.io/v1/image_generation)
  cloudflare/*  → CloudflareImageAdapter  (api.cloudflare.com/client/v4/accounts/)
"""

import base64
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AuthenticationError, ProviderError, RateLimitError
from app.adapters.cloudflare_image import CloudflareImageAdapter
from app.adapters.gemini_image import GeminiImageAdapter
from app.adapters.image_base import ImageAdapter
from app.adapters.minimax_image import MinimaxImageAdapter
from app.adapters.nvidia_image import NvidiaImageAdapter
from app.constants import GEMINI_IMAGE
from app.db import get_db
from app.models import Session as DBSession
from app.services.events import publish_complete, publish_session_start

# Type alias for database dependency
DbDep = Annotated[AsyncSession, Depends(get_db)]

logger = logging.getLogger(__name__)

router = APIRouter()


class ImageGenerationRequest(BaseModel):
    """Request body for image generation."""

    prompt: str = Field(..., description="Text description of desired image")
    project_id: str = Field(..., description="Project ID for session tracking (required)")
    model: str = Field(
        default=GEMINI_IMAGE,
        description="Model identifier for image generation",
    )
    size: str = Field(default="1024x1024", description="Image dimensions")
    style: str | None = Field(default=None, description="Style hint (e.g., photorealistic)")
    reference_image: str | None = Field(
        default=None,
        description="Base64-encoded reference image for style/character consistency",
    )
    reference_mime_type: str = Field(
        default="image/png",
        description="MIME type of the reference image",
    )
    agent_slug: str | None = Field(
        default=None,
        description="Agent slug for agent-based image generation (optional)",
    )


class ImageGenerationResponse(BaseModel):
    """Response body for image generation."""

    image_base64: str = Field(..., description="Base64-encoded image data")
    mime_type: str = Field(..., description="MIME type (e.g., image/png)")
    model: str = Field(..., description="Model used for generation")
    provider: str = Field(..., description="Provider that served the request")
    session_id: str = Field(..., description="Session ID for tracking")


# Per-provider adapter cache (keyed by provider name)
_adapters: dict[str, ImageAdapter] = {}


def _get_image_adapter(model: str) -> ImageAdapter:
    """Return the cached image adapter for the given model's provider."""
    provider = model.split("/")[0] if "/" in model else "gemini"
    if provider not in _adapters:
        if provider == "nvidia":
            _adapters["nvidia"] = NvidiaImageAdapter()
            logger.info("Created NvidiaImageAdapter")
        elif provider == "minimax":
            _adapters["minimax"] = MinimaxImageAdapter()
            logger.info("Created MinimaxImageAdapter")
        elif provider == "cloudflare":
            _adapters["cloudflare"] = CloudflareImageAdapter()
            logger.info("Created CloudflareImageAdapter")
        else:
            _adapters["gemini"] = GeminiImageAdapter()
            logger.info("Created GeminiImageAdapter")
    return _adapters.get(provider) or _adapters.setdefault("gemini", GeminiImageAdapter())


def clear_image_adapter_cache() -> None:
    """Clear the image adapter cache. Useful for testing."""
    _adapters.clear()


async def _create_image_session(
    db: AsyncSession,
    project_id: str,
    model: str,
    provider: str,
) -> DBSession:
    """Create a session for image generation."""
    session_id = str(uuid.uuid4())
    session = DBSession(
        id=session_id,
        project_id=project_id,
        provider=provider,
        model=model,
        status="active",
        session_type="image_generation",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.post("/generate-image", response_model=ImageGenerationResponse)
async def generate_image(
    request: ImageGenerationRequest,
    db: DbDep,
) -> ImageGenerationResponse:
    """Generate an image from a text prompt.

    Routes to Gemini, NVIDIA NIM, MiniMax, or Cloudflare based on the model prefix.
    Creates a session for tracking.
    """
    provider = request.model.split("/")[0] if "/" in request.model else "gemini"

    # Create session for tracking
    session = await _create_image_session(db, request.project_id, request.model, provider)
    session_id = session.id

    # Publish session start event
    await publish_session_start(session_id, request.model, request.project_id)

    # Decode reference image from base64 if provided (before try block so
    # HTTPException isn't caught by the generic Exception handler below)
    ref_image_bytes: bytes | None = None
    if request.reference_image:
        try:
            ref_image_bytes = base64.b64decode(request.reference_image)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 reference_image: {e}") from e

    try:
        adapter = _get_image_adapter(request.model)

        result = await adapter.generate_image(
            prompt=request.prompt,
            model=request.model,
            size=request.size,
            style=request.style,
            reference_image=ref_image_bytes,
            reference_mime_type=request.reference_mime_type,
        )

        # Update session status to completed
        session.status = "completed"
        await db.commit()

        # Publish complete event (image gen doesn't have tokens in same way)
        await publish_complete(session_id, input_tokens=0, output_tokens=0, cost=0.0)

        # Encode image as base64
        image_base64 = base64.b64encode(result.image_data).decode("utf-8")

        return ImageGenerationResponse(
            image_base64=image_base64,
            mime_type=result.mime_type,
            model=result.model,
            provider=result.provider,
            session_id=session_id,
        )

    except ValueError as e:
        logger.error("Configuration error: %s", e)
        session.status = "failed"
        await db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Configuration error: {e}. Check provider credentials in Settings or environment.",
        ) from e

    except RateLimitError as e:
        logger.warning("Rate limit for %s", e.provider)
        session.status = "failed"
        await db.commit()
        retry_after = str(int(e.retry_after)) if e.retry_after else "60"
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded for {e.provider}. Wait {retry_after}s.",
            headers={"Retry-After": retry_after},
        ) from e

    except AuthenticationError as e:
        logger.error("Auth error for %s", e.provider)
        session.status = "failed"
        await db.commit()
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed for {e.provider}. Check credentials in Settings or environment.",
        ) from e

    except ProviderError as e:
        logger.error("Provider error: %s", e)
        session.status = "failed"
        await db.commit()
        status_code = e.status_code or 500
        detail = str(e)
        if e.retriable:
            detail += " This error may be transient; retry may succeed."
        raise HTTPException(status_code=status_code, detail=detail) from e

    except Exception as e:
        logger.exception("Unexpected error in /generate-image: %s", e)
        session.status = "failed"
        await db.commit()
        raise HTTPException(
            status_code=500,
            detail="Internal server error. Check logs for details.",
        ) from e
