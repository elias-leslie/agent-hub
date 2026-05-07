"""Tests for image generation routing."""

from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock

from agent_hub import AgentHubClient, AsyncAgentHubClient, DEFAULT_IMAGE_AGENT


def _image_response() -> dict[str, str]:
    return {
        "image_base64": "aGVsbG8=",
        "mime_type": "image/png",
        "model": "served-image-model",
        "provider": "served-image-provider",
        "session_id": "sess-image",
    }


def test_generate_image_defaults_to_image_agent(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://localhost:8003/api/generate-image",
        method="POST",
        json=_image_response(),
    )

    with AgentHubClient() as client:
        response = client.generate_image(
            prompt="sprite",
            project_id="agent-hub",
        )

    request = httpx_mock.get_request()
    assert request is not None
    body = json.loads(request.content)
    assert body["agent_slug"] == DEFAULT_IMAGE_AGENT
    assert "model" not in body
    assert response.model == "served-image-model"


@pytest.mark.asyncio
async def test_generate_image_accepts_explicit_agent_slug(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://localhost:8003/api/generate-image",
        method="POST",
        json=_image_response(),
    )

    async with AsyncAgentHubClient() as client:
        await client.generate_image(
            prompt="mockup",
            project_id="summitflow",
            agent_slug="product-mockup-designer",
        )

    request = httpx_mock.get_request()
    assert request is not None
    body = json.loads(request.content)
    assert body["agent_slug"] == "product-mockup-designer"
    assert "model" not in body
