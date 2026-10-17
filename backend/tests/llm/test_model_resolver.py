from __future__ import annotations

from app.config import settings
from app.llm.model_resolver import resolve_llm_model
from app.llm.types import OpenAICompletionsCompat
from tests.model_ids import MODEL_CATALOG


def test_gemini_uses_google_sdk_default_endpoint() -> None:
    model = resolve_llm_model("gemini-2.5-flash-lite", "gemini")

    assert model.api == "google-generative-ai"
    assert model.base_url == ""
    assert "audio" in model.input


def test_nvidia_catalog_id_maps_to_upstream_model_id() -> None:
    model = resolve_llm_model("nvidia/glm-5.3", "nvidia")

    assert model.id == "z-ai/glm-5.3"
    assert model.base_url == "https://integrate.api.nvidia.com/v1"


def test_minimax_uses_minimax_anthropic_compatible_endpoint() -> None:
    model = resolve_llm_model("minimax/MiniMax-M2.7", "minimax")

    assert model.api == "anthropic-messages"
    assert model.id == "MiniMax-M2.7"
    assert model.base_url == "https://api.minimax.io/anthropic"


def test_kimi_code_uses_anthropic_compatible_membership_endpoint() -> None:
    model = resolve_llm_model("kimi-code/kimi-for-coding", "kimi-code")

    assert model.api == "anthropic-messages"
    assert model.id == "kimi-for-coding"
    assert model.base_url == "https://api.kimi.com/coding"
    assert model.headers == {"User-Agent": "KimiCLI/1.5"}


def test_codex_uses_chatgpt_codex_responses_endpoint() -> None:
    model = resolve_llm_model("codex/gpt-6-luna", "codex")

    assert model.api == "openai-codex-responses"
    assert model.id == "gpt-6-luna"
    assert model.base_url == "https://chatgpt.com/backend-api/codex/responses"
    assert "audio" not in model.input


def test_cloudflare_catalog_id_maps_to_workers_ai_model_id(monkeypatch) -> None:
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")

    model = resolve_llm_model("cloudflare/gpt-oss-120b", "cloudflare")

    assert model.id == "@cf/openai/gpt-oss-120b"
    assert model.base_url == "https://api.cloudflare.com/client/v4/accounts/acct-123/ai/v1"


def test_local_qwen_keeps_shared_endpoint_and_request_semantics(monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_openai_base_url", "http://127.0.0.1:11434/v1")
    model = resolve_llm_model("local/qwen3.8-27b-gsq-rco-iq3_s", "local")
    assert model.id == "qwen3.8-27b-gsq-rco-iq3_s"
    assert model.base_url == settings.local_openai_base_url
    assert isinstance(model.compat, OpenAICompletionsCompat)
    assert model.compat.thinking_format == "qwen-chat-template"
    assert model.compat.reasoning_budget_tokens == {"low": 512, "medium": 1024, "xhigh": 2048}


def test_seed_catalog_does_not_restore_neri_experiment_model() -> None:
    assert all(entry.id != "local/qwen3.8-27b-gsq-rco-iq3_s-mtp" for entry in MODEL_CATALOG)
    assert all(entry.alias != "local/neri-qwen" for entry in MODEL_CATALOG)
