"""Model ID constants and provider groupings."""

from __future__ import annotations

# =============================================================================
# Model Constants - SINGLE SOURCE OF TRUTH
# =============================================================================
# Update these when new model versions are released.
# All code should import from here, not hardcode model strings.

# Claude models (Anthropic)
CLAUDE_SONNET = "claude-sonnet-4-6"
CLAUDE_OPUS = "claude-opus-4-6"
CLAUDE_HAIKU = "claude-haiku-4-5"

# Gemini 3 models (Google)
GEMINI_FLASH = "gemini-3-flash-preview"
GEMINI_PRO = "gemini-3-pro-preview"
GEMINI_3_1_PRO = "gemini-3.1-pro-preview"
GEMINI_IMAGE = "gemini-3-pro-image-preview"

# New experimental models
GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"

# OpenRouter Models (Canonical IDs) — only models cheaper/exclusive on OR
OR_KIMI_K2_5 = "openrouter/moonshotai/kimi-k2.5"
OR_FREE_TRINITY = "openrouter/arcee-ai/trinity-large-preview:free"
OR_FREE_GLM = "openrouter/z-ai/glm-4.5-air:free"

# OpenAI models (Direct)
OPENAI_GPT_5_2 = "openai/gpt-5.2"
OPENAI_GPT_5_3_CODEX = "openai/gpt-5.3-codex"
OPENAI_GPT_NANO = "openai/gpt-5-nano"

# Codex models (ChatGPT subscription via OAuth)
CODEX_GPT_5_3 = "codex/gpt-5.3-codex"
CODEX_GPT_5_2 = "codex/gpt-5.2"
CODEX_GPT_5_1_MINI = "codex/gpt-5.1-codex-mini"

# xAI models (Direct)
XAI_GROK_CODE_FAST = "xai/grok-code-fast-1"
XAI_GROK_4_1_FAST = "xai/grok-4.1-fast"

# Zhipu models (Direct)
ZHIPU_GLM_5 = "zhipu/glm-5"
ZHIPU_GLM_4_7 = "zhipu/glm-4.7"

# MiniMax models (Direct)
MINIMAX_M2_5 = "minimax/MiniMax-M2.5"

# Default models for each use case
DEFAULT_CLAUDE_MODEL = CLAUDE_SONNET
DEFAULT_GEMINI_MODEL = GEMINI_FLASH

# Model for complex reasoning (code review, architecture decisions)
REASONING_CLAUDE_MODEL = CLAUDE_OPUS
REASONING_GEMINI_MODEL = GEMINI_3_1_PRO

# Model for fast/cheap operations (extraction, validation, summarization)
FAST_CLAUDE_MODEL = CLAUDE_HAIKU
FAST_GEMINI_MODEL = GEMINI_FLASH
