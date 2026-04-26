from __future__ import annotations

from pathlib import Path

DOC = Path(__file__).resolve().parents[3] / "docs" / "agent-hub-primary-chat-contract.md"


def test_primary_chat_contract_documents_ownership_and_clients() -> None:
    text = DOC.read_text(encoding="utf-8")

    required_phrases = [
        "Agent Hub owns the primary interactive agent UI",
        "SummitFlow owns:",
        "Browser extension bubble:",
        "Codex, Claude Code, Jenny, and other TUIs:",
        "must not own:",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_primary_chat_contract_keeps_browser_events_app_visible_by_default() -> None:
    text = DOC.read_text(encoding="utf-8")

    required_events = [
        "browser_page_state_updated",
        "browser_annotation_created",
        "browser_control_requested",
        "browser_user_message",
        "browser_teardown",
    ]

    for event in required_events:
        assert event in text

    assert "Runtime and browser events are app-visible by default" in text
    assert "They become model-visible only through compact context selection" in text


def test_primary_chat_contract_records_pi_mono_adaptation() -> None:
    text = DOC.read_text(encoding="utf-8")

    assert "Pi-mono Comparison" in text
    assert "Event-first runtime" in text
    assert "Local JSONL as Agent Hub source of truth" in text
    assert "Provider-specific artifact extraction in adapters" in text
    assert "Pi-mono tree entries map to Agent Hub" in text
