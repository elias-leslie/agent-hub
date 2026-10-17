"""Model-adjacent constants that are not catalog data.

The model catalog itself (ids, aliases, scores, costs, capabilities) lives only in
the DB models/model_aliases tables; refer to models by alias.
"""

from __future__ import annotations

# Placeholder some harness transcripts record for turns without a reported model.
UNKNOWN_MODEL = "unknown"

# Gemini embedding model used by the memory store (768-dim Matryoshka output).
# Stored vectors are tied to it, so it is part of the memory schema, not catalog data.
GEMINI_EMBEDDING = "gemini-embedding-001"

# Provider display names — single source of truth for UI labels.
# Keys match the `provider` field in MODEL_CATALOG entries.
# Kimi Code, MiniMax and OpenRouter stay listed: their credentials are stored
# and their catalog rows can be re-enabled once the account is funded.
PROVIDER_NAMES: dict[str, str] = {
    "claude": "Claude",
    "gemini": "Gemini",
    "kimi-code": "Kimi Code",
    "local": "Local",
    "openrouter": "OpenRouter",
    "xai": "xAI",
    "minimax": "MiniMax",
    "nvidia": "NVIDIA",
    "cloudflare": "Cloudflare",
    "codex": "Codex",
}
