"""Typed native model provenance survives both client session response shapes."""

from agent_hub.models.session import SessionListItem, SessionResponse


def test_session_models_retain_current_native_evidence():
    payload = {
        "id": "child", "project_id": "agent-hub", "parent_session_id": "root",
        "provider": "codex", "model": "codex/unknown", "requested_model": "codex/gpt-6.1-sol",
        "effective_model": "codex/unknown", "status": "active", "message_count": 0,
        "created_at": "2026-09-30T15:00:00Z", "updated_at": "2026-09-30T15:00:00Z",
        "model_evidence": {
            "session_id": "child", "native_session_id": "root", "turn_id": "turn",
            "source": "codex_transcript", "source_path": "/tmp/native.jsonl",
            "source_generation": "generation", "source_line": 12,
            "source_timestamp": "2026-09-30T15:00:00Z", "requested_model": "gpt-6.1-sol",
            "requested_reasoning_effort": "high", "observed_model": None,
        },
    }
    for schema in (SessionResponse, SessionListItem):
        response = schema.model_validate(payload)
        assert response.parent_session_id == "root"
        assert response.requested_model == "codex/gpt-6.1-sol"
        assert response.model_evidence is not None
        assert response.model_evidence.requested_reasoning_effort == "high"
        assert response.model_evidence.session_id == "child"
        assert response.model_evidence.native_session_id == "root"
        assert response.model_evidence.observed_model is None
