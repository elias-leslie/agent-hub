"""The generic completion surface cannot bypass the passive local-worker boundary."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.complete.endpoints import complete
from app.api.complete.schemas import CompletionRequest
from app.constants.models import LOCAL_NERI_QWEN3_8_27B_IQ3_S


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("agent_slug", "model"),
    [
        ("neri-local-candidate", None),
        ("another-agent", LOCAL_NERI_QWEN3_8_27B_IQ3_S),
    ],
)
async def test_generic_completion_rejects_local_candidate_before_orchestration(
    agent_slug: str,
    model: str | None,
) -> None:
    request = CompletionRequest(
        agent_slug=agent_slug,
        model=model,
        project_id="security-research",
        messages=[{"role": "user", "content": "run tools"}],
        tools=[
            {
                "name": "bash",
                "description": "shell",
                "input_schema": {"type": "object"},
            }
        ],
        execute_tools=True,
        max_turns=4,
    )
    with patch(
        "app.api.complete.endpoints.orchestrate_completion", new=AsyncMock()
    ) as orchestrate, pytest.raises(HTTPException) as error:
        await complete(request, SimpleNamespace(state=SimpleNamespace()), None, AsyncMock())
    assert error.value.status_code == 400
    orchestrate.assert_not_awaited()


def test_restricted_runtime_resolver_fails_closed_without_dedicated_opt_in() -> None:
    from app.llm.model_resolver import resolve_llm_model

    with pytest.raises(ValueError, match="dedicated execution boundary"):
        resolve_llm_model(LOCAL_NERI_QWEN3_8_27B_IQ3_S, "local")
