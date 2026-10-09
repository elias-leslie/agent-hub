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
GEMINI_3_8_FLASH = "gemini-3.8-flash"
GEMINI_3_7_FLASH = "gemini-3.7-flash"
GEMINI_3_6_FLASH = "gemini-3.6-flash"
GEMINI_3_5_FLASH = "gemini-3.5-flash"
GEMINI_3_5_FLASH_LITE = "gemini-3.5-flash-lite"
GEMINI_3_1_FLASH_LITE = "gemini-3.1-flash-lite"

# Gemini embedding model used by the memory store (768-dim Matryoshka output).
GEMINI_EMBEDDING = "gemini-embedding-001"

# Gemini 2.5 models (Google)
GEMINI_2_5_FLASH = "gemini-2.5-flash"
GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"

# Codex models (ChatGPT subscription via OAuth). Only models the ChatGPT-account
# Codex endpoint serves; it rejects gpt-5.1/5.2/5.3-codex and gpt-5.4(-mini).
CODEX_GPT_6_1_SOL = "codex/gpt-6.1-sol"
CODEX_GPT_6_ASTRA = "codex/gpt-6-astra"
CODEX_GPT_6_SOL = "codex/gpt-6-sol"
CODEX_GPT_6_LUNA = "codex/gpt-6-luna"
CODEX_GPT_5_6_SOL = "codex/gpt-5.6-sol"
CODEX_GPT_5_6_TERRA = "codex/gpt-5.6-terra"
CODEX_GPT_5_6_LUNA = "codex/gpt-5.6-luna"
CODEX_GPT_DAYBREAK_BLUE = "codex/gpt-daybreak-blue-latest"
CODEX_GPT_5_5 = "codex/gpt-5.5"

# xAI models (Direct)
XAI_GROK_4_3 = "xai/grok-4.3"
XAI_GROK_4_20 = "xai/grok-4.20-0309-reasoning"
XAI_GROK_4_20_MULTI_AGENT = "xai/grok-4.20-multi-agent-0309"

# NVIDIA NIM models (Free tier — chat)
# Verified live against integrate.api.nvidia.com on 2026-10-09. NIM retires models
# aggressively (410 Gone with an EOL date), so re-probe before adding a new id here.
NVIDIA_GLM_5_3 = "nvidia/glm-5.3"
NVIDIA_GPT_OSS_20B = "nvidia/gpt-oss-20b"
NVIDIA_NEMOTRON_3_SUPER = "nvidia/nemotron-3-super-120b-a12b"
NVIDIA_NEMOTRON_3_5_LIGHTNING = "nvidia/nemotron-3.5-lightning-30b-a3b"

# NVIDIA NIM image generation models (ai.api.nvidia.com/v1/genai/)
NVIDIA_FLUX_1_DEV = "nvidia/flux.1-dev"
NVIDIA_FLUX_1_KONTEXT = "nvidia/flux.1-kontext-dev"

# Cloudflare Workers AI models (Free tier — 10k Neurons/day)
CF_LLAMA_4_SCOUT = "cloudflare/llama-4-scout-17b"
CF_QWEN3_30B = "cloudflare/qwen3-30b"
CF_QWQ_32B = "cloudflare/qwq-32b"
CF_MISTRAL_SMALL = "cloudflare/mistral-small-3.1-24b"
CF_QWEN2_5_CODER = "cloudflare/qwen2.5-coder-32b"
CF_GLM_4_7_FLASH = "cloudflare/glm-4.7-flash"
CF_GPT_OSS_120B = "cloudflare/gpt-oss-120b"
CF_GPT_OSS_20B = "cloudflare/gpt-oss-20b"
CF_GEMMA_4_26B = "cloudflare/gemma-4-26b"
CF_GRANITE_4_H_MICRO = "cloudflare/granite-4.0-h-micro"
CF_NEMOTRON_3_120B = "cloudflare/nemotron-3-120b"

# Local OpenAI-compatible models (Ollama/vLLM/llama.cpp server)
LOCAL_GEMMA_4_12B = "local/gemma4:12b-it-qat"
LOCAL_QWEN3_8_27B_IQ3_S = "local/qwen3.8-27b-gsq-rco-iq3_s"
# Document/receipt vision. Use the *-instruct tag explicitly: the bare ``qwen3-vl:8b``
# tag resolves to the same weights as ``qwen3-vl:8b-thinking`` (verified by manifest
# digest ed12a4674d72), whose reasoning cannot be turned off and which returns an
# empty content string on long extractions.
LOCAL_QWEN3_VL_8B_INSTRUCT = "local/qwen3-vl:8b-instruct"
LOCAL_EMBEDDINGGEMMA_300M = "local/embeddinggemma:300m"

# Cloudflare Workers AI image generation models
CF_FLUX_2_KLEIN_9B = "cloudflare/flux-2-klein-9b"
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
DEFAULT_GEMINI_MODEL = GEMINI_3_8_FLASH

# Model for complex reasoning (code review, architecture decisions). No Gemini
# Pro model has free-tier quota on our keys, so this is the strongest Flash.
REASONING_GEMINI_MODEL = GEMINI_3_8_FLASH

# Model for fast/cheap operations (extraction, validation, summarization)
FAST_GEMINI_MODEL = GEMINI_3_1_FLASH_LITE
