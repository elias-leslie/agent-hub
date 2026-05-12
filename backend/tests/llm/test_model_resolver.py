from __future__ import annotations

from app.llm.model_resolver import resolve_llm_model


def test_gemini_uses_google_sdk_default_endpoint() -> None:
    model = resolve_llm_model("gemini-2.5-flash-lite", "gemini")

    assert model.api == "google-generative-ai"
    assert model.base_url == ""
