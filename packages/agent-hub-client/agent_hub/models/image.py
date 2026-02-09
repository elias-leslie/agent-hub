"""Image generation models for Agent Hub client."""

from pydantic import BaseModel, Field


class ImageGenerationResponse(BaseModel):
    """Response from image generation endpoint."""

    image_base64: str = Field(..., description="Base64-encoded image data")
    mime_type: str = Field(..., description="MIME type (e.g., image/png)")
    model: str = Field(..., description="Model used for generation")
    provider: str = Field(..., description="Provider that served the request")
    session_id: str = Field(..., description="Session ID for tracking")
