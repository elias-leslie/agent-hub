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
CLAUDE_OPUS_4_7 = "claude-opus-4-7"
CLAUDE_HAIKU = "claude-haiku-4-5"

# Gemini 3 models (Google)
GEMINI_FLASH = "gemini-3-flash-preview"
GEMINI_PRO = "gemini-3-pro-preview"
GEMINI_3_1_PRO = "gemini-3.1-pro-preview"
GEMINI_3_1_FLASH_LITE = "gemini-3.1-flash-lite-preview"
GEMINI_IMAGE = "gemini-3-pro-image-preview"
GEMINI_IMAGE_NANO = "gemini-2.5-flash-image"            # Nano Banana - stable, fast
GEMINI_IMAGE_NANO2 = "gemini-3.1-flash-image-preview"   # Nano Banana 2 - preview, fastest

# New experimental models
GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"

# OpenRouter Models (Canonical IDs) — only models cheaper/exclusive on OR
OR_KIMI_K2_5 = "openrouter/moonshotai/kimi-k2.5"
OR_FREE_TRINITY = "openrouter/arcee-ai/trinity-large-preview:free"
OR_FREE_GLM = "openrouter/z-ai/glm-4.5-air:free"

# OpenAI models (Direct)
OPENAI_GPT_5_2 = "openai/gpt-5.2"
OPENAI_GPT_NANO = "openai/gpt-5-nano"

# Codex models (ChatGPT subscription via OAuth)
CODEX_GPT_5_4 = "codex/gpt-5.4"
CODEX_GPT_5_3 = "codex/gpt-5.3-codex"
CODEX_GPT_5_3_SPARK = "codex/gpt-5.3-codex-spark"
CODEX_GPT_5_2 = "codex/gpt-5.2-codex"
CODEX_GPT_5_1 = "codex/gpt-5.1-codex"
CODEX_GPT_5_1_MINI = "codex/gpt-5.1-codex-mini"

# xAI models (Direct)
XAI_GROK_CODE_FAST = "xai/grok-code-fast-1"
XAI_GROK_4_1_FAST = "xai/grok-4-1-fast-reasoning"
XAI_GROK_4_20 = "xai/grok-4.20-reasoning"
XAI_GROK_4_20_MULTI_AGENT = "xai/grok-4.20-multi-agent"

# Zhipu models (Direct)
ZHIPU_GLM_5 = "zhipu/glm-5"
ZHIPU_GLM_4_7 = "zhipu/glm-4.7"

# MiniMax models (Direct)
MINIMAX_M2_5 = "minimax/MiniMax-M2.5"
MINIMAX_IMAGE_01 = "minimax/image-01"

# NVIDIA NIM models (Free tier — chat)
NVIDIA_QWEN_3_5 = "nvidia/qwen3.5-397b-a17b"
NVIDIA_MINIMAX_M2_5 = "nvidia/minimax-m2.5"
NVIDIA_KIMI_K2_5 = "nvidia/kimi-k2.5"

# NVIDIA NIM image generation models (ai.api.nvidia.com/v1/genai/)
NVIDIA_FLUX_1_DEV = "nvidia/flux.1-dev"
NVIDIA_FLUX_1_SCHNELL = "nvidia/flux.1-schnell"
NVIDIA_FLUX_1_KONTEXT = "nvidia/flux.1-kontext-dev"
NVIDIA_SD_3_5_LARGE = "nvidia/stable-diffusion-3.5-large"

# Cloudflare Workers AI models (Free tier — 10k Neurons/day)
CF_LLAMA_4_SCOUT = "cloudflare/llama-4-scout-17b"
CF_QWEN3_30B = "cloudflare/qwen3-30b"
CF_QWQ_32B = "cloudflare/qwq-32b"
CF_MISTRAL_SMALL = "cloudflare/mistral-small-3.1-24b"
CF_QWEN2_5_CODER = "cloudflare/qwen2.5-coder-32b"

# Cloudflare Workers AI image generation models
CF_FLUX_2_DEV = "cloudflare/flux-2-dev"
CF_FLUX_1_SCHNELL = "cloudflare/flux-1-schnell"
CF_SD_XL_LIGHTNING = "cloudflare/sd-xl-lightning"
CF_LEONARDO_PHOENIX = "cloudflare/leonardo-phoenix"
CF_LEONARDO_LUCID = "cloudflare/leonardo-lucid-origin"

# Provider display names — single source of truth for UI labels.
# Keys match the `provider` field in MODEL_CATALOG entries.
PROVIDER_NAMES: dict[str, str] = {
    "claude": "Claude",
    "gemini": "Gemini",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "xai": "xAI",
    "zhipu": "Zhipu",
    "minimax": "MiniMax",
    "nvidia": "NVIDIA",
    "cloudflare": "Cloudflare",
    "codex": "Codex",
}

# Default models for each use case
DEFAULT_CLAUDE_MODEL = CLAUDE_SONNET
DEFAULT_GEMINI_MODEL = GEMINI_FLASH

# Model for complex reasoning (code review, architecture decisions)
REASONING_CLAUDE_MODEL = CLAUDE_OPUS_4_7
REASONING_GEMINI_MODEL = GEMINI_3_1_PRO

# Model for fast/cheap operations (extraction, validation, summarization)
FAST_CLAUDE_MODEL = CLAUDE_HAIKU
FAST_GEMINI_MODEL = GEMINI_3_1_FLASH_LITE
