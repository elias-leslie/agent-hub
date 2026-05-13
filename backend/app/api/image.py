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
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.cloudflare_image import CloudflareImageAdapter
from app.adapters.gemini_image import GeminiImageAdapter
from app.adapters.image_base import ImageAdapter, ImageGenerationResult
from app.adapters.minimax_image import MinimaxImageAdapter
from app.adapters.nvidia_image import NvidiaImageAdapter
from app.constants import GEMINI_IMAGE, MODEL_CATALOG_BY_ID
from app.db import get_db
from app.models import Session as DBSession
from app.services.agent_model_router import RoutingContext
from app.services.agent_routing_utils import resolve_agent
from app.services.events import publish_complete, publish_session_start
from app.services.llm_errors import AuthenticationError, ProviderError, RateLimitError
from app.services.session_live_activity import mark_session_completed

# Type alias for database dependency
DbDep = Annotated[AsyncSession, Depends(get_db)]

logger = logging.getLogger(__name__)

router = APIRouter()


class ImageGenerationRequest(BaseModel):
    """Request body for image generation."""

    prompt: str = Field(..., description="Text description of desired image")
    project_id: str = Field(..., description="Project ID for session tracking (required)")
    model: str | None = Field(
        default=None,
        description="Deprecated direct model override for image generation",
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
        default="image-gen",
        description="Agent slug for image generation routing",
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


def _is_known_non_image_model(model_id: str) -> bool:
    """True when model is in catalog and explicitly does not support image generation."""
    entry = MODEL_CATALOG_BY_ID.get(model_id)
    if entry is None:
        return False
    return not entry.capabilities.can_generate_images


async def _resolve_model_chain(
    db: AsyncSession,
    request_model: str | None,
    agent_slug: str | None,
) -> list[str]:
    """Build ordered model chain for image generation (primary + fallbacks)."""
    chain = [request_model] if request_model else []

    if agent_slug:
        try:
            resolved = await resolve_agent(
                agent_slug,
                db,
                RoutingContext(),
            )
        except HTTPException:
            resolved = None
        if resolved:
            primary = resolved.model or request_model
            # If caller left default model, honor agent primary first.
            if not request_model or request_model == GEMINI_IMAGE:
                chain = [primary, *(resolved.agent.fallback_models or [])]
            else:
                chain = [request_model, *(resolved.agent.fallback_models or [])]

    seen: set[str] = set()
    filtered: list[str] = []
    for model_id in chain:
        if not model_id:
            continue
        if model_id in seen:
            continue
        seen.add(model_id)
        if _is_known_non_image_model(model_id):
            continue
        filtered.append(model_id)
    if filtered:
        return filtered
    if request_model:
        return [request_model]
    raise ValueError("No image model resolved; configure the image-gen agent.")


async def _create_image_session(
    db: AsyncSession,
    project_id: str,
    model: str,
    provider: str,
    agent_slug: str | None,
) -> DBSession:
    """Create a session for image generation."""
    session_id = str(uuid.uuid4())
    session = DBSession(
        id=session_id,
        project_id=project_id,
        provider=provider,
        model=model,
        agent_slug=agent_slug,
        status="active",
        session_type="image_generation",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def _try_generate_with_fallback(
    model_chain: list[str],
    request: ImageGenerationRequest,
    ref_image_bytes: bytes | None,
    http_request: Request,
) -> ImageGenerationResult:
    """Try models in order, returning the first successful result."""
    last_error: Exception | None = None
    for idx, model_id in enumerate(model_chain):
        try:
            adapter = _get_image_adapter(model_id)
            result = await adapter.generate_image(
                prompt=request.prompt,
                model=model_id,
                size=request.size,
                style=request.style,
                reference_image=ref_image_bytes,
                reference_mime_type=request.reference_mime_type,
            )
            if idx > 0:
                http_request.state.used_fallback = True
                http_request.state.fallback_model = model_id
                logger.info("Image generation fallback succeeded with model=%s", model_id)
            return result
        except (RateLimitError, AuthenticationError, ProviderError, ValueError) as e:
            last_error = e
            logger.warning("Image generation failed for model=%s: %s", model_id, e)

    if last_error:
        raise last_error
    raise ProviderError("No image model could serve the request", provider="image", retriable=False)


async def _complete_image_generation(
    session: DBSession,
    db: AsyncSession,
    result: ImageGenerationResult,
    session_id: str,
) -> ImageGenerationResponse:
    """Update session to completed and build the response."""
    session.provider = result.provider
    session.model = result.model
    mark_session_completed(
        session,
        summary="Image generation completed",
        termination_reason=None,
    )
    await db.commit()
    await publish_complete(session_id, input_tokens=0, output_tokens=0, cost=0.0)
    image_base64 = base64.b64encode(result.image_data).decode("utf-8")
    return ImageGenerationResponse(
        image_base64=image_base64,
        mime_type=result.mime_type,
        model=result.model,
        provider=result.provider,
        session_id=session_id,
    )


async def _fail_and_raise(session: DBSession, db: AsyncSession, exc: Exception) -> NoReturn:
    """Mark session as failed and raise the appropriate HTTPException."""
    session.status = "failed"
    await db.commit()
    if isinstance(exc, ValueError):
        logger.error("Configuration error: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Configuration error: {exc}. Check provider credentials in Settings or environment.",
        ) from exc
    if isinstance(exc, RateLimitError):
        logger.warning("Rate limit for %s", exc.provider)
        retry_after = str(int(exc.retry_after)) if exc.retry_after else "60"
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded for {exc.provider}. Wait {retry_after}s.",
            headers={"Retry-After": retry_after},
        ) from exc
    if isinstance(exc, AuthenticationError):
        logger.error("Auth error for %s", exc.provider)
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed for {exc.provider}. Check credentials in Settings or environment.",
        ) from exc
    if isinstance(exc, ProviderError):
        logger.error("Provider error: %s", exc)
        status_code = exc.status_code or 500
        detail = str(exc)
        if exc.retriable:
            detail += " This error may be transient; retry may succeed."
        raise HTTPException(status_code=status_code, detail=detail) from exc
    logger.exception("Unexpected error in /generate-image: %s", exc)
    raise HTTPException(status_code=500, detail="Internal server error. Check logs for details.") from exc


@router.post("/generate-image", response_model=ImageGenerationResponse)
async def generate_image(
    request: ImageGenerationRequest,
    db: DbDep,
    http_request: Request,
) -> ImageGenerationResponse:
    """Generate an image from a text prompt.

    Routes to Gemini, NVIDIA NIM, MiniMax, or Cloudflare based on the model prefix.
    Creates a session for tracking.
    """
    http_request.state.used_fallback = False
    http_request.state.fallback_model = None
    model_chain = await _resolve_model_chain(db, request.model, request.agent_slug)
    requested_model = request.model or model_chain[0]
    provider = requested_model.split("/")[0] if "/" in requested_model else "gemini"

    session = await _create_image_session(
        db, request.project_id, requested_model, provider, request.agent_slug
    )
    session_id = session.id
    await publish_session_start(session_id, requested_model, request.project_id)

    ref_image_bytes: bytes | None = None
    if request.reference_image:
        try:
            ref_image_bytes = base64.b64decode(request.reference_image)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 reference_image: {e}") from e

    try:
        result = await _try_generate_with_fallback(model_chain, request, ref_image_bytes, http_request)
        return await _complete_image_generation(session, db, result, session_id)

    except HTTPException:
        raise

    except Exception as e:
        await _fail_and_raise(session, db, e)
        raise  # unreachable; _fail_and_raise always raises
