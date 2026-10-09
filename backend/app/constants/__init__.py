"""Shared constants used across the application.

This module re-exports constants from submodules for backward compatibility.
"""
# ruff: noqa: F401

from __future__ import annotations

from app.constants.catalog import (
    MODEL_ALIASES,
    MODEL_CATALOG,
    MODEL_CATALOG_BY_ID,
    MODEL_REGISTRY,
    SCORE_WEIGHTS,
    VALID_CLAUDE_MODELS,
    VALID_CLOUDFLARE_MODELS,
    VALID_CODEX_MODELS,
    VALID_DEEPSEEK_MODELS,
    VALID_GEMINI_MODELS,
    VALID_KIMI_CODE_MODELS,
    VALID_LOCAL_MODELS,
    VALID_MINIMAX_MODELS,
    VALID_MOONSHOT_MODELS,
    VALID_NVIDIA_MODELS,
    VALID_OPENAI_MODELS,
    VALID_OPENROUTER_MODELS,
    VALID_XAI_MODELS,
    VALID_ZHIPU_MODELS,
    ModelCapabilities,
    ModelCost,
    ModelEntry,
    ModelScores,
    get_model_capabilities,
    get_model_entry,
    resolve_model,
)
from app.constants.models import (
    CF_FLUX_1_SCHNELL,
    CF_FLUX_2_KLEIN_9B,
    CF_GEMMA_4_26B,
    CF_GLM_4_7_FLASH,
    CF_GPT_OSS_20B,
    CF_GPT_OSS_120B,
    CF_GRANITE_4_H_MICRO,
    CF_LEONARDO_LUCID,
    CF_LEONARDO_PHOENIX,
    CF_LLAMA_4_SCOUT,
    CF_MISTRAL_SMALL,
    CF_NEMOTRON_3_120B,
    CF_QWEN2_5_CODER,
    CF_QWEN3_30B,
    CF_QWQ_32B,
    CF_SD_XL_LIGHTNING,
    CLAUDE_FABLE,
    CLAUDE_HAIKU,
    CLAUDE_OPUS,
    CLAUDE_SONNET,
    CODEX_GPT_5_6_LUNA,
    CODEX_GPT_5_6_SOL,
    CODEX_GPT_5_6_TERRA,
    CODEX_GPT_6_1_SOL,
    CODEX_GPT_6_ASTRA,
    CODEX_GPT_6_LUNA,
    CODEX_GPT_6_SOL,
    CODEX_GPT_DAYBREAK_BLUE,
    DEFAULT_GEMINI_MODEL,
    FAST_GEMINI_MODEL,
    GEMINI_2_5_FLASH_LITE,
    GEMINI_3_1_FLASH_LITE,
    LOCAL_GEMMA_4_12B,
    NVIDIA_FLUX_1_DEV,
    NVIDIA_FLUX_1_KONTEXT,
    PROVIDER_NAMES,
    REASONING_GEMINI_MODEL,
    XAI_GROK_4_3,
    XAI_GROK_4_20,
    XAI_GROK_4_20_MULTI_AGENT,
)
from app.constants.projects import VALID_AGENT_TYPES, VALID_PROJECT_IDS
from app.constants.subtask_types import (
    SUBTASK_TYPE_DESCRIPTIONS,
    SUBTASK_TYPES,
    format_subtask_types_markdown,
)

DEFAULT_RATE_LIMIT_TPM = 100_000

__all__ = [
    name
    for name in globals()
    if (
        name.isupper()
        or name in {
            "ModelCapabilities",
            "ModelCost",
            "ModelEntry",
            "ModelScores",
            "format_subtask_types_markdown",
            "get_model_capabilities",
            "get_model_entry",
            "resolve_model",
        }
    )
]
