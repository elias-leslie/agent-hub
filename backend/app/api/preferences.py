"""Preferences API - User preference management."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    CLAUDE_HAIKU,
    CLAUDE_OPUS,
    CLAUDE_SONNET,
    DEFAULT_CLAUDE_MODEL,
    GEMINI_FLASH,
    GEMINI_PRO,
)
from app.db import get_db
from app.storage.preferences import (
    get_preferences_async,
    upsert_preferences_async,
)

router = APIRouter()


# Valid options
VALID_VERBOSITY = {"concise", "normal", "detailed"}
VALID_TONE = {"professional", "friendly", "technical"}
VALID_MODELS = {
    CLAUDE_SONNET,
    CLAUDE_OPUS,
    CLAUDE_HAIKU,
    GEMINI_FLASH,
    GEMINI_PRO,
}


# Request/Response schemas
class PreferencesUpdate(BaseModel):
    """Request body for updating preferences."""

    verbosity: str | None = Field(None, description="Response verbosity level")
    tone: str | None = Field(None, description="Response tone")
    default_model: str | None = Field(None, description="Default model for new conversations")


class PreferencesResponse(BaseModel):
    """Response body for preferences."""

    verbosity: str
    tone: str
    default_model: str


def get_user_id(x_user_id: Annotated[str | None, Header()] = None) -> str:
    """Get user ID from header or use default."""
    # In a real implementation, this would come from authentication
    # For now, use a header or default to "default-user"
    return x_user_id or "default-user"


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[str, Depends(get_user_id)],
) -> PreferencesResponse:
    """Get user preferences."""
    prefs = await get_preferences_async(db, user_id)

    if not prefs:
        # Return defaults
        return PreferencesResponse(
            verbosity="normal",
            tone="professional",
            default_model=DEFAULT_CLAUDE_MODEL,
        )

    return PreferencesResponse(
        verbosity=prefs.verbosity,
        tone=prefs.tone,
        default_model=prefs.default_model,
    )


@router.put("/preferences", response_model=PreferencesResponse)
async def update_preferences(
    request: PreferencesUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: Annotated[str, Depends(get_user_id)],
) -> PreferencesResponse:
    """Update user preferences."""
    # Validate values
    if request.verbosity and request.verbosity not in VALID_VERBOSITY:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid verbosity. Must be one of: {', '.join(VALID_VERBOSITY)}",
        )

    if request.tone and request.tone not in VALID_TONE:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tone. Must be one of: {', '.join(VALID_TONE)}",
        )

    if request.default_model and request.default_model not in VALID_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid default_model. Must be one of: {', '.join(VALID_MODELS)}",
        )

    prefs = await upsert_preferences_async(
        db,
        user_id=user_id,
        verbosity=request.verbosity,
        tone=request.tone,
        default_model=request.default_model,
    )

    return PreferencesResponse(
        verbosity=prefs.verbosity,
        tone=prefs.tone,
        default_model=prefs.default_model,
    )
