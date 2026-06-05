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
    CF_GLM_4_7_FLASH,
    CLAUDE_HAIKU,
    CLAUDE_OPUS_4_7,
    CLAUDE_SONNET,
    CODEX_GPT_5_1,
    CODEX_GPT_5_2,
    CODEX_GPT_5_3,
    CODEX_GPT_5_4,
    CODEX_GPT_5_4_MINI,
    CODEX_GPT_5_5,
    DEEPSEEK_V4_FLASH,
    GEMINI_3_1_FLASH_LITE,
    GEMINI_3_1_PRO,
    KIMI_CODE_FOR_CODING,
    LOCAL_QWEN3_CODER_30B_A3B,
    MINIMAX_M2_7,
    MOONSHOT_KIMI_K2_6,
    NVIDIA_QWEN_3_5,
    OPENAI_GPT_5_4_MINI,
    OR_KIMI_K2_6,
    XAI_GROK_4_3,
    ZHIPU_GLM_4_7_FLASHX,
)

__all__ = [
    "MODEL_ALIASES",
    "MODEL_CATALOG",
    "MODEL_CATALOG_BY_ID",
    "MODEL_REGISTRY",
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

        # Legacy dated Claude aliases retained in existing agent rows.
        "claude-haiku-4-5-20251001": CLAUDE_HAIKU,
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
