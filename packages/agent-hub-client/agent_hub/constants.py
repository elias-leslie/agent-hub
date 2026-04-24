"""Model constants for Agent Hub.

Single source of truth for LLM model identifiers.
Update here when new model versions are released.
Keep in sync with backend/app/constants/models.py.
"""

# Claude models (Anthropic)
CLAUDE_SONNET = "claude-sonnet-4-6"
CLAUDE_OPUS = "claude-opus-4-6"
CLAUDE_HAIKU = "claude-haiku-4-5"

# Gemini 3 models (Google)
GEMINI_FLASH = "gemini-3-flash-preview"
GEMINI_PRO = "gemini-3-pro-preview"
GEMINI_3_1_PRO = "gemini-3.1-pro-preview"
GEMINI_3_1_FLASH_LITE = "gemini-3.1-flash-lite-preview"
GEMINI_IMAGE = "gemini-3-pro-image-preview"

# Codex models (ChatGPT subscription via Agent Hub)
CODEX_GPT_5_5 = "codex/gpt-5.5"

# Default models for each use case
DEFAULT_CLAUDE_MODEL = CLAUDE_SONNET
DEFAULT_GEMINI_MODEL = GEMINI_FLASH

# Model for complex reasoning
REASONING_CLAUDE_MODEL = CLAUDE_OPUS
REASONING_GEMINI_MODEL = GEMINI_3_1_PRO

# Model for fast/cheap operations
FAST_CLAUDE_MODEL = CLAUDE_HAIKU
FAST_GEMINI_MODEL = GEMINI_3_1_FLASH_LITE
DEFAULT_IMAGE_MODEL = GEMINI_IMAGE
