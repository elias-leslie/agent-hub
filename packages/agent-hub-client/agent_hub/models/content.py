"""Content and message models for Agent Hub client."""

from datetime import datetime
from typing import Literal, Union

from pydantic import BaseModel, Field


class TextContent(BaseModel):
    """Text content block."""

    type: Literal["text"] = "text"
    text: str = Field(..., description="Text content")


class ImageContent(BaseModel):
    """Image content block for vision API.

    Format compatible with Anthropic's vision API:
    - type: "image"
    - source: contains base64 encoded image data
    """

    type: Literal["image"] = "image"
    source: dict[str, str] = Field(
        ...,
        description="Image source with type='base64', media_type, and data fields",
    )

    @classmethod
    def from_base64(cls, data: str, media_type: str = "image/png") -> "ImageContent":
        """Create image content from base64 encoded data.

        Args:
            data: Base64 encoded image data (without prefix).
            media_type: MIME type (image/png, image/jpeg, image/gif, image/webp).

        Returns:
            ImageContent ready for API.
        """
        return cls(
            source={
                "type": "base64",
                "media_type": media_type,
                "data": data,
            }
        )


# Content can be text string, TextContent, or ImageContent
ContentBlock = Union[str, TextContent, ImageContent]


class MessageInput(BaseModel):
    """Input message for completion request."""

    role: Literal["user", "assistant", "system"] = Field(
        ..., description="Message role"
    )
    content: str | list[ContentBlock] = Field(
        ..., description="Message content - string or list of content blocks"
    )


class Message(BaseModel):
    """Message with full metadata (from session history)."""

    id: int
    role: str
    content: str
    tokens: int | None = None
    created_at: datetime
