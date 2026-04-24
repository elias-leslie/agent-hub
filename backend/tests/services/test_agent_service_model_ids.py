from app.services.agent_service import _canonicalize_model_chain, _canonicalize_model_id


def test_canonicalize_model_id_resolves_legacy_codex_aliases() -> None:
    assert _canonicalize_model_id("codex/gpt-5.2") == "codex/gpt-5.2-codex"
    assert _canonicalize_model_id("codex/gpt-5.3") == "codex/gpt-5.3-codex"
    assert _canonicalize_model_id("codex/gpt-5.4") == "codex/gpt-5.4"
    assert _canonicalize_model_id("codex") == "codex/gpt-5.5"


def test_canonicalize_model_chain_dedupes_after_alias_resolution() -> None:
    assert _canonicalize_model_chain(
        [
            "codex/gpt-5.2",
            "codex/gpt-5.2-codex",
            "claude-sonnet-4-6",
            "claude-sonnet-4-6",
        ]
    ) == ["codex/gpt-5.2-codex", "claude-sonnet-4-6"]
