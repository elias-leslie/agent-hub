"""Utility functions for Gemini adapter.

This module re-exports functions from focused submodules for backward compatibility.
All functionality has been split into specialized modules:
- gemini_messages: Message and content conversion
- gemini_config: Configuration building
- gemini_response: Response processing
- gemini_errors: Error handling
"""

from app.adapters.gemini_config import build_config
from app.adapters.gemini_errors import handle_error
from app.adapters.gemini_messages import build_parts, convert_messages
from app.adapters.gemini_response import process_response

__all__ = [
    "build_config",
    "build_parts",
    "convert_messages",
    "handle_error",
    "process_response",
]
