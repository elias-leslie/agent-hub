from app.services.agent_service import _canonicalize_model_chain, _canonicalize_model_id


def test_canonicalize_model_id_resolves_codex_aliases() -> None:
    assert _canonicalize_model_id("codex-sol") == "codex/gpt-5.6-sol"
    assert _canonicalize_model_id("codex-6-luna") == "codex/gpt-6-luna"
    assert _canonicalize_model_id("codex/gpt-5.5") == "codex/gpt-5.5"
    assert _canonicalize_model_id("codex") == "codex/gpt-6.1-sol"


def test_canonicalize_model_chain_dedupes_after_alias_resolution() -> None:
    assert _canonicalize_model_chain(
        [
            "codex-sol",
            "codex/gpt-5.6-sol",
            "claude-sonnet-4-6",
            "claude-sonnet-4-6",
        ]
    ) == ["codex/gpt-5.6-sol", "claude-sonnet-4-6"]
