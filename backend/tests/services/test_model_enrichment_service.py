from app.constants import MODEL_CATALOG
from app.services.model_enrichment_service import _build_discovery_summary


def test_build_discovery_summary_only_tracks_first_party_providers() -> None:
    summary = _build_discovery_summary(
        [
            {"id": "grok-4.20-0309-reasoning", "provider_id": "x-ai", "provider_name": "xAI"},
            {"id": "grok-4.1", "provider_id": "x-ai", "provider_name": "xAI"},
            {"id": "grok-4.1", "provider_id": "302ai", "provider_name": "302.AI"},
            {"id": "grok-4.20-reasoning", "provider_id": "nano-gpt", "provider_name": "NanoGPT"},
            {"id": "claude-sonnet-4-6", "provider_id": "anthropic", "provider_name": "Anthropic"},
            {"id": "claude-opus-5", "provider_id": "anthropic", "provider_name": "Anthropic"},
            {"id": "claude-opus-5", "provider_id": "llmgateway", "provider_name": "LLM Gateway"},
        ],
        list(MODEL_CATALOG),
    )

    assert summary["unmatched_model_count"] == 2
    assert summary["unmatched_provider_count"] == 2
    assert [provider["provider_id"] for provider in summary["top_providers"]] == ["claude", "xai"]
    assert summary["sample_model_ids"] == ["claude-opus-5", "grok-4.1"]
