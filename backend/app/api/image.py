"""Image generation API endpoint."""

import base64
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AuthenticationError, ProviderError, RateLimitError
from app.adapters.gemini_image import GeminiImageAdapter
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
    purpose: str | None = Field(
        default=None,
        description="Purpose of this generation (e.g., mockup_generation)",
    )
    model: str = Field(
        default=GEMINI_IMAGE,
        description="Model identifier for image generation",
    )
    size: str = Field(default="1024x1024", description="Image dimensions")
    style: str | None = Field(default=None, description="Style hint (e.g., photorealistic)")


class ImageGenerationResponse(BaseModel):
    """Response body for image generation."""

    image_base64: str = Field(..., description="Base64-encoded image data")
    mime_type: str = Field(..., description="MIME type (e.g., image/png)")
    model: str = Field(..., description="Model used for generation")
    provider: str = Field(..., description="Provider that served the request")
    session_id: str = Field(..., description="Session ID for tracking")


# Cached adapter instance
_image_adapter: GeminiImageAdapter | None = None


def _get_image_adapter() -> GeminiImageAdapter:
    """Get cached image adapter instance."""
    global _image_adapter
    if _image_adapter is None:
        _image_adapter = GeminiImageAdapter()
        logger.info("Created GeminiImageAdapter")
    return _image_adapter


def clear_image_adapter_cache() -> None:
    """Clear the image adapter cache. Useful for testing."""
    global _image_adapter
    _image_adapter = None


async def _create_image_session(
    db: AsyncSession,
    project_id: str,
    model: str,
    purpose: str | None = None,
) -> DBSession:
    """Create a session for image generation."""
    session_id = str(uuid.uuid4())
    session = DBSession(
        id=session_id,
        project_id=project_id,
        provider="gemini",
        model=model,
        status="active",
        purpose=purpose,
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

    Routes to Gemini image generation model. Creates a session for tracking.
    """
    # Create session for tracking
    session = await _create_image_session(
        db,
        request.project_id,
        request.model,
        request.purpose,
    )
    session_id = session.id

    # Publish session start event
    await publish_session_start(session_id, request.model, request.project_id)

    try:
        adapter = _get_image_adapter()

        result = await adapter.generate_image(
            prompt=request.prompt,
            model=request.model,
            size=request.size,
            style=request.style,
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
        logger.error(f"Configuration error: {e}")
        session.status = "failed"
        await db.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Configuration error: {e}. Check GEMINI_API_KEY.",
        ) from e

    except RateLimitError as e:
        logger.warning(f"Rate limit for {e.provider}")
        session.status = "failed"
        await db.commit()
        retry_after = str(int(e.retry_after)) if e.retry_after else "60"
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded for {e.provider}. Wait {retry_after}s.",
            headers={"Retry-After": retry_after},
        ) from e

    except AuthenticationError as e:
        logger.error(f"Auth error for {e.provider}")
        session.status = "failed"
        await db.commit()
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed for {e.provider}. Verify GEMINI_API_KEY.",
        ) from e

    except ProviderError as e:
        logger.error(f"Provider error: {e}")
        session.status = "failed"
        await db.commit()
        status_code = e.status_code or 500
        detail = str(e)
        if e.retriable:
            detail += " This error may be transient; retry may succeed."
        raise HTTPException(status_code=status_code, detail=detail) from e

    except Exception as e:
        logger.exception(f"Unexpected error in /generate-image: {e}")
        session.status = "failed"
        await db.commit()
        raise HTTPException(
            status_code=500,
            detail="Internal server error. Check logs for details.",
        ) from e
