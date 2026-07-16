from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.complete.complete_orchestrator import _validate_and_resolve
from app.api.complete.schemas import CompletionRequest
from app.api.complete.validation import validate_audio_capability


def _audio_request() -> CompletionRequest:
    return CompletionRequest(
        agent_slug="game-audio-critic",
        project_id="test-project",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "audio",
                        "source": {
                            "type": "base64",
                            "media_type": "audio/wav",
                            "data": "UklGRg==",
                        },
                    }
                ],
            }
        ],
    )


def test_audio_capability_allows_declared_audio_model() -> None:
    validate_audio_capability(_audio_request(), "gemini-2.5-flash-lite")


@pytest.mark.asyncio
async def test_resolution_rejects_audio_for_model_without_capability() -> None:
    request = _audio_request()
    http_request = SimpleNamespace(state=SimpleNamespace(allowed_projects=None))

    with (
        patch(
            "app.api.complete.complete_orchestrator.validate_agent_slug",
            new_callable=AsyncMock,
        ),
        patch("app.api.complete.complete_orchestrator.validate_project_access"),
        patch(
            "app.api.complete.complete_orchestrator.resolve_agent_and_model",
            new_callable=AsyncMock,
            return_value=(
                "codex/gpt-5.4-mini",
                "codex",
                None,
                None,
                "game-audio-critic",
            ),
        ),
        patch(
            "app.api.complete.complete_orchestrator.apply_mention_override",
            return_value=("codex/gpt-5.4-mini", "codex"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await _validate_and_resolve(request, http_request, None)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == {
        "error": "unsupported_input_modality",
        "model": "codex/gpt-5.4-mini",
        "modality": "audio",
        "message": "Model 'codex/gpt-5.4-mini' does not support audio input.",
    }
