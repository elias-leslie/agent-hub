"""Runtime model catalog with scores, costs, and capabilities.

Re-exports all public symbols from submodules so existing imports continue to work:
  from app.constants.catalog import MODEL_CATALOG, ModelEntry, resolve_model, ...

Runtime data is hydrated from the DB ``models`` and ``model_aliases`` tables at
startup. ``catalog_entries.MODEL_CATALOG`` is retained as insert-only seed data.
"""

from __future__ import annotations

from app.constants.catalog_entries import MODEL_CATALOG as SEED_MODEL_CATALOG
from app.constants.catalog_types import (
    SCORE_WEIGHTS,
    ModelCapabilities,
    ModelCost,
    ModelEntry,
    ModelScores,
)
from app.constants.models import (
    CF_GEMMA_4_26B,
    CF_GLM_4_7_FLASH,
    CF_GPT_OSS_20B,
    CF_GPT_OSS_120B,
    CF_GRANITE_4_H_MICRO,
    CF_KIMI_K2_5,
    CF_KIMI_K2_6,
    CF_LLAMA_4_SCOUT,
    CF_MISTRAL_SMALL,
    CF_NEMOTRON_3_120B,
    CF_QWEN2_5_CODER,
    CF_QWEN3_30B,
    CF_QWQ_32B,
    CLAUDE_HAIKU,
    CLAUDE_OPUS_4_7,
    CLAUDE_SONNET,
    CODEX_GPT_5_1,
    CODEX_GPT_5_1_MINI,
    CODEX_GPT_5_2,
    CODEX_GPT_5_3,
    CODEX_GPT_5_3_SPARK,
    CODEX_GPT_5_4,
    CODEX_GPT_5_4_MINI,
    CODEX_GPT_5_5,
    DEEPSEEK_V4_FLASH,
    DEEPSEEK_V4_PRO,
    GEMINI_2_5_FLASH_LITE,
    GEMINI_3_1_FLASH_LITE,
    GEMINI_3_1_PRO,
    GEMINI_FLASH,
    KIMI_CODE_FOR_CODING,
    LOCAL_QWEN2_5_CODER_14B,
    LOCAL_QWEN3_30B_A3B,
    LOCAL_QWEN3_CODER_30B_A3B,
    MINIMAX_M2_5,
    MINIMAX_M2_5_HIGHSPEED,
    MINIMAX_M2_7,
    MINIMAX_M2_7_HIGHSPEED,
    MOONSHOT_KIMI_K2_5,
    MOONSHOT_KIMI_K2_6,
    NVIDIA_DEEPSEEK_V4_FLASH,
    NVIDIA_KIMI_K2_6,
    NVIDIA_MINIMAX_M2_7,
    NVIDIA_QWEN_3_5,
    OPENAI_GPT_5_4,
    OPENAI_GPT_5_4_MINI,
    OPENAI_GPT_5_4_NANO,
    OPENAI_GPT_5_4_PRO,
    OPENAI_GPT_5_5,
    OR_KIMI_K2_6,
    XAI_GROK_4_3,
    XAI_GROK_4_20,
    XAI_GROK_4_20_MULTI_AGENT,
    ZHIPU_GLM_4_7,
    ZHIPU_GLM_4_7_FLASH,
    ZHIPU_GLM_4_7_FLASHX,
    ZHIPU_GLM_5,
    ZHIPU_GLM_5_1,
    ZHIPU_GLM_5_TURBO,
)

__all__ = [
    "CLAUDE_TO_GEMINI_MAP",
    "CLOUDFLARE_TO_CLAUDE_MAP",
    "CODEX_TO_CLAUDE_MAP",
    "DEEPSEEK_TO_CLAUDE_MAP",
    "GEMINI_TO_CLAUDE_MAP",
    "LOCAL_TO_CLAUDE_MAP",
    "MINIMAX_TO_CLAUDE_MAP",
    "MODEL_ALIASES",
    "MODEL_CATALOG",
    "MODEL_CATALOG_BY_ID",
    "MODEL_REGISTRY",
    "MOONSHOT_TO_CLAUDE_MAP",
    "NVIDIA_TO_CLAUDE_MAP",
    "OPENAI_TO_CLAUDE_MAP",
    "SCORE_WEIGHTS",
    "VALID_CLAUDE_MODELS",
    "VALID_CLOUDFLARE_MODELS",
    "VALID_CODEX_MODELS",
    "VALID_DEEPSEEK_MODELS",
    "VALID_GEMINI_MODELS",
    "VALID_KIMI_CODE_MODELS",
    "VALID_LOCAL_MODELS",
    "VALID_MINIMAX_MODELS",
    "VALID_MOONSHOT_MODELS",
    "VALID_NVIDIA_MODELS",
    "VALID_OPENAI_MODELS",
    "VALID_OPENROUTER_MODELS",
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
    "replace_runtime_model_catalog",
    "resolve_model",
    "seed_alias_overrides",
]

# ---------------------------------------------------------------------------
# Derived lookups — built once at import time from MODEL_CATALOG
# ---------------------------------------------------------------------------

MODEL_CATALOG: list[ModelEntry] = list(SEED_MODEL_CATALOG)
MODEL_REGISTRY: list[dict[str, str]] = []
MODEL_CATALOG_BY_ID: dict[str, ModelEntry] = {}
MODEL_ALIASES: dict[str, str] = {}


def seed_alias_overrides() -> dict[str, str]:
    """Return seed/default aliases that are stored in DB on first boot."""
    return {
        # Bare provider names resolve to current default model for that provider.
        "claude": CLAUDE_SONNET,
        "cloudflare": CF_GLM_4_7_FLASH,
        "codex": CODEX_GPT_5_5,
        "deepseek": DEEPSEEK_V4_FLASH,
        "gemini": GEMINI_3_1_FLASH_LITE,
        "kimi-code": KIMI_CODE_FOR_CODING,
        "pro": GEMINI_3_1_PRO,
        "local": LOCAL_QWEN3_CODER_30B_A3B,
        "minimax": MINIMAX_M2_7,
        "moonshot": MOONSHOT_KIMI_K2_6,
        "nvidia": NVIDIA_QWEN_3_5,
        "openai": OPENAI_GPT_5_4_MINI,
        "openrouter": OR_KIMI_K2_6,
        "xai": XAI_GROK_4_3,
        "zhipu": ZHIPU_GLM_4_7_FLASHX,

        # Exact legacy aliases only. These do not substitute one model for another.
        "codex/gpt-5.1": CODEX_GPT_5_1,
        "codex/gpt-5.2": CODEX_GPT_5_2,
        "codex/gpt-5.3": CODEX_GPT_5_3,
        "codex/gpt-5.4": CODEX_GPT_5_4,
        "codex/gpt-5.4-mini": CODEX_GPT_5_4_MINI,
        "codex/gpt-5.5": CODEX_GPT_5_5,

        # CloudCode aliases
        "cc/sonnet": CLAUDE_SONNET,
        "cc/opus": CLAUDE_OPUS_4_7,
        "opus-4.7": CLAUDE_OPUS_4_7,
        "cc/opus-4.7": CLAUDE_OPUS_4_7,
        "cloudcode/claude-sonnet-4-6": CLAUDE_SONNET,
        "cloudcode/claude-opus-4-6-thinking": CLAUDE_OPUS_4_7,
        "cloudcode/claude-opus-4-7": CLAUDE_OPUS_4_7,
    }


def _default_aliases(entries: list[ModelEntry]) -> dict[str, str]:
    valid_ids = {entry.id for entry in entries}
    aliases = {entry.alias.lower(): entry.id for entry in entries if entry.alias}
    aliases.update({
        alias.lower(): model_id
        for alias, model_id in seed_alias_overrides().items()
        if model_id in valid_ids
    })
    return aliases


def _refresh_valid_model_globals() -> None:
    global VALID_CLAUDE_MODELS
    global VALID_CLOUDFLARE_MODELS
    global VALID_CODEX_MODELS
    global VALID_DEEPSEEK_MODELS
    global VALID_GEMINI_MODELS
    global VALID_KIMI_CODE_MODELS
    global VALID_LOCAL_MODELS
    global VALID_MINIMAX_MODELS
    global VALID_MOONSHOT_MODELS
    global VALID_NVIDIA_MODELS
    global VALID_OPENAI_MODELS
    global VALID_OPENROUTER_MODELS
    global VALID_XAI_MODELS
    global VALID_ZHIPU_MODELS

    VALID_CLAUDE_MODELS = _models_for_provider("claude")
    VALID_CLOUDFLARE_MODELS = _models_for_provider("cloudflare")
    VALID_CODEX_MODELS = _models_for_provider("codex")
    VALID_DEEPSEEK_MODELS = _models_for_provider("deepseek")
    VALID_GEMINI_MODELS = _models_for_provider("gemini")
    VALID_KIMI_CODE_MODELS = _models_for_provider("kimi-code")
    VALID_LOCAL_MODELS = _models_for_provider("local")
    VALID_MINIMAX_MODELS = _models_for_provider("minimax")
    VALID_MOONSHOT_MODELS = _models_for_provider("moonshot")
    VALID_NVIDIA_MODELS = _models_for_provider("nvidia")
    VALID_OPENAI_MODELS = _models_for_provider("openai")
    VALID_OPENROUTER_MODELS = _models_for_provider("openrouter")
    VALID_XAI_MODELS = _models_for_provider("xai")
    VALID_ZHIPU_MODELS = _models_for_provider("zhipu")


def replace_runtime_model_catalog(
    entries: list[ModelEntry],
    aliases: dict[str, str] | None = None,
) -> None:
    """Replace process-local catalog snapshot while preserving imported containers."""
    MODEL_CATALOG[:] = list(entries)
    MODEL_REGISTRY[:] = [
        {"id": e.id, "alias": e.alias, "name": e.name, "hint": e.hint, "provider": e.provider}
        for e in MODEL_CATALOG
    ]
    MODEL_CATALOG_BY_ID.clear()
    MODEL_CATALOG_BY_ID.update({e.id: e for e in MODEL_CATALOG})
    MODEL_ALIASES.clear()
    MODEL_ALIASES.update(aliases or _default_aliases(MODEL_CATALOG))
    _refresh_valid_model_globals()


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


VALID_CLAUDE_MODELS: tuple[str, ...] = ()
VALID_CLOUDFLARE_MODELS: tuple[str, ...] = ()
VALID_CODEX_MODELS: tuple[str, ...] = ()
VALID_DEEPSEEK_MODELS: tuple[str, ...] = ()
VALID_GEMINI_MODELS: tuple[str, ...] = ()
VALID_KIMI_CODE_MODELS: tuple[str, ...] = ()
VALID_LOCAL_MODELS: tuple[str, ...] = ()
VALID_MINIMAX_MODELS: tuple[str, ...] = ()
VALID_MOONSHOT_MODELS: tuple[str, ...] = ()
VALID_NVIDIA_MODELS: tuple[str, ...] = ()
VALID_OPENAI_MODELS: tuple[str, ...] = ()
VALID_OPENROUTER_MODELS: tuple[str, ...] = ()
VALID_XAI_MODELS: tuple[str, ...] = ()
VALID_ZHIPU_MODELS: tuple[str, ...] = ()

replace_runtime_model_catalog(MODEL_CATALOG)

# ---------------------------------------------------------------------------
# Model tier mappings for fallback routing
# ---------------------------------------------------------------------------

CLAUDE_TO_GEMINI_MAP: dict[str, str] = {
    CLAUDE_HAIKU: GEMINI_3_1_FLASH_LITE,
    CLAUDE_SONNET: GEMINI_FLASH,
    CLAUDE_OPUS_4_7: GEMINI_3_1_PRO,
}

GEMINI_TO_CLAUDE_MAP: dict[str, str] = {
    GEMINI_FLASH: CLAUDE_SONNET,
    GEMINI_3_1_PRO: CLAUDE_OPUS_4_7,
    GEMINI_3_1_FLASH_LITE: CLAUDE_HAIKU,
    GEMINI_2_5_FLASH_LITE: CLAUDE_HAIKU,
}

OPENAI_TO_CLAUDE_MAP: dict[str, str] = {
    OPENAI_GPT_5_4_NANO: CLAUDE_HAIKU,
    OPENAI_GPT_5_4_MINI: CLAUDE_SONNET,
    OPENAI_GPT_5_4: CLAUDE_OPUS_4_7,
    OPENAI_GPT_5_5: CLAUDE_OPUS_4_7,
    OPENAI_GPT_5_4_PRO: CLAUDE_OPUS_4_7,
}

CODEX_TO_CLAUDE_MAP: dict[str, str] = {
    CODEX_GPT_5_1_MINI: CLAUDE_HAIKU,
    CODEX_GPT_5_1: CLAUDE_SONNET,
    CODEX_GPT_5_2: CLAUDE_OPUS_4_7,
    CODEX_GPT_5_3_SPARK: CLAUDE_SONNET,
    CODEX_GPT_5_3: CLAUDE_OPUS_4_7,
    CODEX_GPT_5_4_MINI: CLAUDE_SONNET,
    CODEX_GPT_5_4: CLAUDE_OPUS_4_7,
    CODEX_GPT_5_5: CLAUDE_OPUS_4_7,
}

XAI_TO_CLAUDE_MAP: dict[str, str] = {
    XAI_GROK_4_3: CLAUDE_SONNET,
    XAI_GROK_4_20: CLAUDE_OPUS_4_7,
    XAI_GROK_4_20_MULTI_AGENT: CLAUDE_OPUS_4_7,
}

ZHIPU_TO_CLAUDE_MAP: dict[str, str] = {
    ZHIPU_GLM_5_1: CLAUDE_OPUS_4_7,
    ZHIPU_GLM_5: CLAUDE_SONNET,
    ZHIPU_GLM_5_TURBO: CLAUDE_SONNET,
    ZHIPU_GLM_4_7: CLAUDE_SONNET,
    ZHIPU_GLM_4_7_FLASHX: CLAUDE_HAIKU,
    ZHIPU_GLM_4_7_FLASH: CLAUDE_HAIKU,
}

MINIMAX_TO_CLAUDE_MAP: dict[str, str] = {
    MINIMAX_M2_7: CLAUDE_SONNET,
    MINIMAX_M2_7_HIGHSPEED: CLAUDE_SONNET,
    MINIMAX_M2_5: CLAUDE_SONNET,
    MINIMAX_M2_5_HIGHSPEED: CLAUDE_SONNET,
}

MOONSHOT_TO_CLAUDE_MAP: dict[str, str] = {
    MOONSHOT_KIMI_K2_6: CLAUDE_OPUS_4_7,
    MOONSHOT_KIMI_K2_5: CLAUDE_SONNET,
}

DEEPSEEK_TO_CLAUDE_MAP: dict[str, str] = {
    DEEPSEEK_V4_FLASH: CLAUDE_SONNET,
    DEEPSEEK_V4_PRO: CLAUDE_OPUS_4_7,
}

LOCAL_TO_CLAUDE_MAP: dict[str, str] = {
    LOCAL_QWEN3_CODER_30B_A3B: CLAUDE_SONNET,
    LOCAL_QWEN3_30B_A3B: CLAUDE_HAIKU,
    LOCAL_QWEN2_5_CODER_14B: CLAUDE_HAIKU,
}

NVIDIA_TO_CLAUDE_MAP: dict[str, str] = {
    NVIDIA_QWEN_3_5: CLAUDE_SONNET,
    NVIDIA_DEEPSEEK_V4_FLASH: CLAUDE_SONNET,
    NVIDIA_MINIMAX_M2_7: CLAUDE_SONNET,
    NVIDIA_KIMI_K2_6: CLAUDE_OPUS_4_7,
}

CLOUDFLARE_TO_CLAUDE_MAP: dict[str, str] = {
    CF_KIMI_K2_6: CLAUDE_OPUS_4_7,
    CF_KIMI_K2_5: CLAUDE_SONNET,
    CF_GLM_4_7_FLASH: CLAUDE_HAIKU,
    CF_QWEN3_30B: CLAUDE_HAIKU,
    CF_GPT_OSS_120B: CLAUDE_SONNET,
    CF_GPT_OSS_20B: CLAUDE_HAIKU,
    CF_LLAMA_4_SCOUT: CLAUDE_HAIKU,
    CF_QWQ_32B: CLAUDE_SONNET,
    CF_MISTRAL_SMALL: CLAUDE_HAIKU,
    CF_QWEN2_5_CODER: CLAUDE_SONNET,
    CF_GEMMA_4_26B: CLAUDE_HAIKU,
    CF_GRANITE_4_H_MICRO: CLAUDE_HAIKU,
    CF_NEMOTRON_3_120B: CLAUDE_SONNET,
}
