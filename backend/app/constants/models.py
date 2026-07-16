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
GEMINI_3_5_FLASH = "gemini-3.5-flash"
GEMINI_FLASH = "gemini-3-flash-preview"
GEMINI_3_1_PRO = "gemini-3.1-pro-preview"
GEMINI_3_1_FLASH_LITE = "gemini-3.1-flash-lite"
GEMINI_3_1_FLASH_LITE_PREVIEW = "gemini-3.1-flash-lite-preview"
GEMINI_IMAGE = "gemini-3-pro-image-preview"
GEMINI_IMAGE_NANO = "gemini-2.5-flash-image"            # Nano Banana - stable, fast
GEMINI_IMAGE_NANO2 = "gemini-3.1-flash-image-preview"   # Nano Banana 2 - preview, fastest

# Gemini 2.5 models (Google)
GEMINI_2_5_FLASH = "gemini-2.5-flash"
GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"
GEMINI_2_5_PRO = "gemini-2.5-pro"

# OpenRouter Models (Canonical IDs) — only models cheaper/exclusive on OR
OR_KIMI_K2_6 = "openrouter/moonshotai/kimi-k2.6"
OR_KIMI_K2_5 = "openrouter/moonshotai/kimi-k2.5"  # Legacy/superseded by K2.6
OR_FREE_TRINITY = "openrouter/arcee-ai/trinity-large-preview:free"
OR_FREE_GLM = "openrouter/z-ai/glm-4.5-air:free"

# OpenAI models (Direct)
OPENAI_GPT_5_5 = "openai/gpt-5.5"
OPENAI_GPT_5_4 = "openai/gpt-5.4"
OPENAI_GPT_5_4_MINI = "openai/gpt-5.4-mini"
OPENAI_GPT_5_4_NANO = "openai/gpt-5.4-nano"
OPENAI_GPT_5_4_PRO = "openai/gpt-5.4-pro"
OPENAI_GPT_5_2 = "openai/gpt-5.2"
OPENAI_GPT_5_2_PRO = "openai/gpt-5.2-pro"
OPENAI_GPT_NANO = "openai/gpt-5-nano"

# Codex models (ChatGPT subscription via OAuth)
CODEX_GPT_5_5 = "codex/gpt-5.5"
CODEX_GPT_5_4 = "codex/gpt-5.4"
CODEX_GPT_5_4_MINI = "codex/gpt-5.4-mini"
CODEX_GPT_5_3 = "codex/gpt-5.3-codex"
CODEX_GPT_5_3_SPARK = "codex/gpt-5.3-codex-spark"
CODEX_GPT_5_2 = "codex/gpt-5.2-codex"
CODEX_GPT_5_1 = "codex/gpt-5.1-codex"
CODEX_GPT_5_1_MINI = "codex/gpt-5.1-codex-mini"

# xAI models (Direct)
XAI_GROK_4_3 = "xai/grok-4.3"
XAI_GROK_4_20 = "xai/grok-4.20-0309-reasoning"
XAI_GROK_4_20_MULTI_AGENT = "xai/grok-4.20-multi-agent-0309"

# Zhipu models (Direct)
ZHIPU_GLM_5_1 = "zhipu/glm-5.1"
ZHIPU_GLM_5 = "zhipu/glm-5"
ZHIPU_GLM_5_TURBO = "zhipu/glm-5-turbo"
ZHIPU_GLM_4_7 = "zhipu/glm-4.7"
ZHIPU_GLM_4_7_FLASHX = "zhipu/glm-4.7-flashx"
ZHIPU_GLM_4_7_FLASH = "zhipu/glm-4.7-flash"

# MiniMax models (Direct)
MINIMAX_M3 = "minimax/MiniMax-M3"
MINIMAX_M2_7 = "minimax/MiniMax-M2.7"
MINIMAX_M2_7_HIGHSPEED = "minimax/MiniMax-M2.7-highspeed"
MINIMAX_M2_5 = "minimax/MiniMax-M2.5"
MINIMAX_M2_5_HIGHSPEED = "minimax/MiniMax-M2.5-highspeed"
MINIMAX_IMAGE_01 = "minimax/image-01"

# Kimi Code models (subscription)
KIMI_CODE_FOR_CODING = "kimi-code/kimi-for-coding"

# Moonshot/Kimi models (Direct)
MOONSHOT_KIMI_K2_6 = "moonshot/kimi-k2.6"
MOONSHOT_KIMI_K2_5 = "moonshot/kimi-k2.5"

# DeepSeek models (Direct)
DEEPSEEK_V4_FLASH = "deepseek/deepseek-v4-flash"
DEEPSEEK_V4_PRO = "deepseek/deepseek-v4-pro"

# NVIDIA NIM models (Free tier — chat)
NVIDIA_QWEN_3_5 = "nvidia/qwen3.5-397b-a17b"
NVIDIA_DEEPSEEK_V4_FLASH = "nvidia/deepseek-v4-flash"
NVIDIA_MINIMAX_M2_7 = "nvidia/minimax-m2.7"
NVIDIA_MINIMAX_M2_5 = "nvidia/minimax-m2.5"  # Legacy/downloadable
NVIDIA_KIMI_K2_6 = "nvidia/kimi-k2.6"
NVIDIA_KIMI_K2_5 = "nvidia/kimi-k2.5"  # Legacy

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
CF_GLM_4_7_FLASH = "cloudflare/glm-4.7-flash"
CF_KIMI_K2_6 = "cloudflare/kimi-k2.6"
CF_KIMI_K2_5 = "cloudflare/kimi-k2.5"
CF_GPT_OSS_120B = "cloudflare/gpt-oss-120b"
CF_GPT_OSS_20B = "cloudflare/gpt-oss-20b"
CF_GEMMA_4_26B = "cloudflare/gemma-4-26b"
CF_GRANITE_4_H_MICRO = "cloudflare/granite-4.0-h-micro"
CF_NEMOTRON_3_120B = "cloudflare/nemotron-3-120b"

# Local OpenAI-compatible models (Ollama/vLLM/llama.cpp server)
LOCAL_QWEN3_CODER_30B_A3B = "local/qwen3-coder:30b-a3b"
LOCAL_QWEN3_30B_A3B = "local/qwen3:30b-a3b"
LOCAL_QWEN2_5_CODER_14B = "local/qwen2.5-coder:14b"
LOCAL_GEMMA_4_12B = "local/gemma4:12b-it-qat"

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
    "deepseek": "DeepSeek",
    "gemini": "Gemini",
    "kimi-code": "Kimi Code",
    "local": "Local",
    "moonshot": "Moonshot",
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
DEFAULT_GEMINI_MODEL = GEMINI_FLASH

# Model for complex reasoning (code review, architecture decisions)
REASONING_GEMINI_MODEL = GEMINI_3_1_PRO

# Model for fast/cheap operations (extraction, validation, summarization)
FAST_GEMINI_MODEL = GEMINI_3_1_FLASH_LITE
