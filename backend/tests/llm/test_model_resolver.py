from __future__ import annotations

from app.llm.model_resolver import resolve_llm_model


def test_gemini_uses_google_sdk_default_endpoint() -> None:
    model = resolve_llm_model("gemini-2.5-flash-lite", "gemini")

    assert model.api == "google-generative-ai"
    assert model.base_url == ""


def test_nvidia_catalog_id_maps_to_upstream_model_id() -> None:
    model = resolve_llm_model("nvidia/kimi-k2.6", "nvidia")

    assert model.id == "moonshotai/kimi-k2.6"
    assert model.base_url == "https://integrate.api.nvidia.com/v1"


def test_minimax_uses_minimax_openai_compatible_endpoint() -> None:
    model = resolve_llm_model("minimax/MiniMax-M2.7", "minimax")

    assert model.api == "openai-completions"
    assert model.id == "MiniMax-M2.7"
    assert model.base_url == "https://api.minimax.io/v1"


def test_kimi_code_uses_anthropic_compatible_membership_endpoint() -> None:
    model = resolve_llm_model("kimi-code/kimi-for-coding", "kimi-code")

    assert model.api == "anthropic-messages"
    assert model.id == "kimi-for-coding"
    assert model.base_url == "https://api.kimi.com/coding/"
    assert model.headers == {"User-Agent": "agent-hub/1.0"}


def test_codex_uses_chatgpt_codex_responses_endpoint() -> None:
    model = resolve_llm_model("codex/gpt-5.4-mini", "codex")

    assert model.api == "openai-codex-responses"
    assert model.id == "gpt-5.4-mini"
    assert model.base_url == "https://chatgpt.com/backend-api/codex/responses"


def test_cloudflare_catalog_id_maps_to_workers_ai_model_id(monkeypatch) -> None:
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")

    model = resolve_llm_model("cloudflare/kimi-k2.6", "cloudflare")

    assert model.id == "@cf/moonshotai/kimi-k2.6"
    assert model.base_url == "https://api.cloudflare.com/client/v4/accounts/acct-123/ai/v1"
