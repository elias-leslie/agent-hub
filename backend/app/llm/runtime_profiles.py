"""Exact runtime identities for models that cannot share provider defaults."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.config import settings
from app.constants.models import LOCAL_NERI_QWEN3_8_27B_IQ3_S
from app.llm.types import OpenAICompletionsCompat

NERI_QWEN_ARTIFACT_SHA256 = (
    "58fd826723939933dc86f45b7fe04545cbc2de1c70f6fe2cdd3858c87a98c12f"
)
NERI_LLAMA_CPP_COMMIT = "f1e44dcc11d8802d107bd7331a3d3fd3e6f57b93"
NERI_REASONING_BUDGET_TOKENS = {"low": 512, "medium": 1_024, "xhigh": 2_048}


@dataclass(frozen=True, slots=True)
class ModelRuntimeProfile:
    """Non-secret execution identity for one specially hosted model."""

    model_id: str
    engine: str
    engine_revision: str
    gpu_backend: str
    server_model_id: str
    artifact_sha256: str
    default_context_tokens: int
    max_concurrency: int
    tool_policy: str
    lifecycle: str
    reasoning_budget_tokens: dict[str, int]

    @property
    def base_url(self) -> str:
        if self.model_id == LOCAL_NERI_QWEN3_8_27B_IQ3_S:
            return settings.neri_local_qwen_base_url
        raise KeyError(f"No runtime endpoint configured for {self.model_id}")

    def public_metadata(self) -> dict[str, Any]:
        data = asdict(self)
        data["base_url"] = self.base_url
        return data


NERI_QWEN_RUNTIME_PROFILE = ModelRuntimeProfile(
    model_id=LOCAL_NERI_QWEN3_8_27B_IQ3_S,
    engine="llama.cpp",
    engine_revision=NERI_LLAMA_CPP_COMMIT,
    gpu_backend="cuda-sm89",
    server_model_id="qwen3.8-27b-neri-iq3_s",
    artifact_sha256=NERI_QWEN_ARTIFACT_SHA256,
    default_context_tokens=32_768,
    max_concurrency=1,
    tool_policy="none",
    lifecycle="experimental",
    reasoning_budget_tokens=NERI_REASONING_BUDGET_TOKENS,
)

_PROFILES = {NERI_QWEN_RUNTIME_PROFILE.model_id: NERI_QWEN_RUNTIME_PROFILE}


def get_model_runtime_profile(model_id: str) -> ModelRuntimeProfile | None:
    """Return a model-specific runtime profile when one is registered."""
    return _PROFILES.get(model_id)


def neri_qwen_compat() -> OpenAICompletionsCompat:
    """llama.cpp/Qwen request semantics, separate from Ollama detection."""
    return OpenAICompletionsCompat(
        supports_store=False,
        supports_developer_role=False,
        supports_reasoning_effort=False,
        supports_usage_in_streaming=True,
        max_tokens_field="max_tokens",
        thinking_format="qwen-chat-template",
        supports_strict_mode=False,
        supports_long_cache_retention=False,
        reasoning_budget_tokens=NERI_REASONING_BUDGET_TOKENS,
        loopback_only_transport=True,
    )


__all__ = [
    "NERI_LLAMA_CPP_COMMIT",
    "NERI_QWEN_ARTIFACT_SHA256",
    "NERI_QWEN_RUNTIME_PROFILE",
    "NERI_REASONING_BUDGET_TOKENS",
    "ModelRuntimeProfile",
    "get_model_runtime_profile",
    "neri_qwen_compat",
]
