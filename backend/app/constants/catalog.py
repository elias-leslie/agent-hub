"""Model catalog with scores, costs, and capabilities.

Re-exports all public symbols from sub-modules so existing imports continue to work:
  from app.constants.catalog import MODEL_CATALOG, ModelEntry, resolve_model, ...
"""

from __future__ import annotations

from app.constants.catalog_entries import MODEL_CATALOG
from app.constants.catalog_types import (
    SCORE_WEIGHTS,
    ModelCapabilities,
    ModelCost,
    ModelEntry,
    ModelScores,
)
from app.constants.models import (
    CF_LLAMA_4_SCOUT,
    CF_MISTRAL_SMALL,
    CF_QWEN2_5_CODER,
    CF_QWEN3_30B,
    CF_QWQ_32B,
    CLAUDE_HAIKU,
    CLAUDE_OPUS,
    CLAUDE_OPUS_4_7,
    CLAUDE_SONNET,
    CODEX_GPT_5_1,
    CODEX_GPT_5_1_MINI,
    CODEX_GPT_5_2,
    CODEX_GPT_5_3,
    CODEX_GPT_5_3_SPARK,
    CODEX_GPT_5_4,
    GEMINI_2_5_FLASH_LITE,
    GEMINI_3_1_FLASH_LITE,
    GEMINI_3_1_PRO,
    GEMINI_FLASH,
    GEMINI_PRO,
    MINIMAX_M2_5,
    NVIDIA_KIMI_K2_5,
    NVIDIA_MINIMAX_M2_5,
    NVIDIA_QWEN_3_5,
    OPENAI_GPT_5_2,
    OPENAI_GPT_NANO,
    XAI_GROK_4_1_FAST,
    XAI_GROK_4_20,
    XAI_GROK_4_20_MULTI_AGENT,
    XAI_GROK_CODE_FAST,
    ZHIPU_GLM_4_7,
    ZHIPU_GLM_5,
)

__all__ = [
    "CLAUDE_TO_GEMINI_MAP",
    "CLOUDFLARE_TO_CLAUDE_MAP",
    "CODEX_TO_CLAUDE_MAP",
    "GEMINI_TO_CLAUDE_MAP",
    "MINIMAX_TO_CLAUDE_MAP",
    "MODEL_ALIASES",
    "MODEL_CATALOG",
    "MODEL_CATALOG_BY_ID",
    "MODEL_REGISTRY",
    "NVIDIA_TO_CLAUDE_MAP",
    "OPENAI_TO_CLAUDE_MAP",
    "SCORE_WEIGHTS",
    "VALID_CLAUDE_MODELS",
    "VALID_CLOUDFLARE_MODELS",
    "VALID_CODEX_MODELS",
    "VALID_GEMINI_MODELS",
    "VALID_MINIMAX_MODELS",
    "VALID_NVIDIA_MODELS",
    "VALID_OPENAI_MODELS",
    "VALID_XAI_MODELS",
    "VALID_ZHIPU_MODELS",
    "XAI_TO_CLAUDE_MAP",
    "ZHIPU_TO_CLAUDE_MAP",
    "ModelCapabilities",
    "ModelCost",
    "ModelEntry",
    "ModelScores",
    "get_model_capabilities",
    "get_model_entry",
    "resolve_model",
]

# ---------------------------------------------------------------------------
# Derived lookups — built once at import time from MODEL_CATALOG
# ---------------------------------------------------------------------------

# Backward-compat: flat dict list for code that imports MODEL_REGISTRY
MODEL_REGISTRY: list[dict[str, str]] = [
    {"id": e.id, "alias": e.alias, "name": e.name, "hint": e.hint, "provider": e.provider}
    for e in MODEL_CATALOG
]

# Lookup by model ID
MODEL_CATALOG_BY_ID: dict[str, ModelEntry] = {e.id: e for e in MODEL_CATALOG}

# Derived from catalog
MODEL_ALIASES: dict[str, str] = {e.alias: e.id for e in MODEL_CATALOG}
MODEL_ALIASES.update({
    # Bare provider names resolve to default model for that provider
    "claude": CLAUDE_SONNET,
    "gemini": GEMINI_FLASH,
    "openai": OPENAI_GPT_5_2,
    # Legacy Codex aliases without the explicit -codex suffix
    "codex/gpt-5.1": CODEX_GPT_5_1,
    "codex/gpt-5.2": CODEX_GPT_5_2,
    "codex/gpt-5.3": CODEX_GPT_5_3,
    # CloudCode aliases
    "cc/sonnet": CLAUDE_SONNET,
    "cc/opus": CLAUDE_OPUS,
    "cc/opus-4.7": CLAUDE_OPUS_4_7,
    "cloudcode/claude-sonnet-4-6": CLAUDE_SONNET,
    "cloudcode/claude-opus-4-6-thinking": CLAUDE_OPUS,
    "cloudcode/claude-opus-4-7": CLAUDE_OPUS_4_7,
})


def resolve_model(alias: str) -> str:
    """Resolve model alias to canonical ID. Pass-through if not an alias."""
    return MODEL_ALIASES.get(alias.lower(), alias)


def get_model_entry(model: str) -> ModelEntry | None:
    """Return the catalog entry for a model id or alias."""
    return MODEL_CATALOG_BY_ID.get(resolve_model(model))


def get_model_capabilities(model: str) -> ModelCapabilities | None:
    """Return model capabilities from the catalog, if known."""
    entry = get_model_entry(model)
    return entry.capabilities if entry else None


def _models_for_provider(provider: str) -> tuple[str, ...]:
    """Derive valid model IDs + aliases for a provider from the catalog."""
    return tuple(
        x
        for entry in MODEL_CATALOG
        if entry.provider == provider
        for x in (entry.id, entry.alias)
    )


# Valid model lists for validation (derived from registry)
VALID_CLAUDE_MODELS = _models_for_provider("claude")
VALID_GEMINI_MODELS = _models_for_provider("gemini")
VALID_CODEX_MODELS = _models_for_provider("codex")
VALID_OPENAI_MODELS = _models_for_provider("openai")
VALID_XAI_MODELS = _models_for_provider("xai")
VALID_ZHIPU_MODELS = _models_for_provider("zhipu")
VALID_MINIMAX_MODELS = _models_for_provider("minimax")
VALID_NVIDIA_MODELS = _models_for_provider("nvidia")
VALID_CLOUDFLARE_MODELS = _models_for_provider("cloudflare")

# ---------------------------------------------------------------------------
# Model tier mappings for fallback routing
# ---------------------------------------------------------------------------

CLAUDE_TO_GEMINI_MAP: dict[str, str] = {
    CLAUDE_HAIKU: GEMINI_FLASH,
    CLAUDE_SONNET: GEMINI_FLASH,
    CLAUDE_OPUS: GEMINI_3_1_PRO,
    CLAUDE_OPUS_4_7: GEMINI_3_1_PRO,
}

GEMINI_TO_CLAUDE_MAP: dict[str, str] = {
    GEMINI_FLASH: CLAUDE_SONNET,
    GEMINI_PRO: CLAUDE_OPUS,
    GEMINI_3_1_PRO: CLAUDE_OPUS,
    GEMINI_3_1_FLASH_LITE: CLAUDE_HAIKU,
    GEMINI_2_5_FLASH_LITE: CLAUDE_HAIKU,
}

OPENAI_TO_CLAUDE_MAP: dict[str, str] = {
    OPENAI_GPT_NANO: CLAUDE_HAIKU,
    OPENAI_GPT_5_2: CLAUDE_SONNET,
}

CODEX_TO_CLAUDE_MAP: dict[str, str] = {
    CODEX_GPT_5_1_MINI: CLAUDE_HAIKU,
    CODEX_GPT_5_1: CLAUDE_SONNET,
    CODEX_GPT_5_2: CLAUDE_OPUS,
    CODEX_GPT_5_3: CLAUDE_OPUS,
    CODEX_GPT_5_3_SPARK: CLAUDE_SONNET,
    CODEX_GPT_5_4: CLAUDE_OPUS,
}

XAI_TO_CLAUDE_MAP: dict[str, str] = {
    XAI_GROK_CODE_FAST: CLAUDE_SONNET,
    XAI_GROK_4_1_FAST: CLAUDE_OPUS,
    XAI_GROK_4_20: CLAUDE_OPUS,
    XAI_GROK_4_20_MULTI_AGENT: CLAUDE_OPUS,
}

ZHIPU_TO_CLAUDE_MAP: dict[str, str] = {
    ZHIPU_GLM_5: CLAUDE_SONNET,
    ZHIPU_GLM_4_7: CLAUDE_SONNET,
}

MINIMAX_TO_CLAUDE_MAP: dict[str, str] = {
    MINIMAX_M2_5: CLAUDE_SONNET,
}

NVIDIA_TO_CLAUDE_MAP: dict[str, str] = {
    NVIDIA_QWEN_3_5: CLAUDE_SONNET,
    NVIDIA_MINIMAX_M2_5: CLAUDE_SONNET,
    NVIDIA_KIMI_K2_5: CLAUDE_SONNET,
}

CLOUDFLARE_TO_CLAUDE_MAP: dict[str, str] = {
    CF_LLAMA_4_SCOUT: CLAUDE_HAIKU,
    CF_QWEN3_30B: CLAUDE_SONNET,
    CF_QWQ_32B: CLAUDE_SONNET,
    CF_MISTRAL_SMALL: CLAUDE_HAIKU,
    CF_QWEN2_5_CODER: CLAUDE_SONNET,
}
