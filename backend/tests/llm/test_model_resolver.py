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


def test_cloudflare_catalog_id_maps_to_workers_ai_model_id(monkeypatch) -> None:
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-123")

    model = resolve_llm_model("cloudflare/kimi-k2.6", "cloudflare")

    assert model.id == "@cf/moonshotai/kimi-k2.6"
    assert model.base_url == "https://api.cloudflare.com/client/v4/accounts/acct-123/ai/v1"
