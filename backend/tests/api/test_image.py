"""Tests for /generate-image endpoint."""

from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.base import AuthenticationError, ProviderError, RateLimitError
from app.adapters.image_base import ImageGenerationResult
from app.api.image import clear_image_adapter_cache
from app.constants import GEMINI_IMAGE
from app.main import app
from tests.conftest import APITestClient


@pytest.fixture
def client():
    """Test client with source headers for kill switch compliance."""
    return APITestClient(app)


@pytest.fixture(autouse=True)
def reset_adapter_cache():
    """Clear adapter cache before each test."""
    clear_image_adapter_cache()
    yield
    clear_image_adapter_cache()


class TestImageGenerationEndpoint:
    """Tests for POST /api/generate-image."""

    @pytest.fixture
    def mock_image_adapter(self):
        """Mock GeminiImageAdapter."""
        with patch("app.api.image.GeminiImageAdapter") as mock:
            adapter = AsyncMock()
            adapter.generate_image = AsyncMock(
                return_value=ImageGenerationResult(
                    image_data=b"fake-image-data",
                    mime_type="image/png",
                    model=GEMINI_IMAGE,
                    provider="gemini",
                    metadata={"size": "1024x1024"},
                )
            )
            mock.return_value = adapter
            yield mock

    def test_generate_image_success(self, client, mock_image_adapter):
        """Test successful image generation."""
        response = client.post(
            "/api/generate-image",
            json={
                "prompt": "A beautiful sunset over mountains",
                "project_id": "test-project",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["mime_type"] == "image/png"
        assert data["provider"] == "gemini"
        assert "session_id" in data
        assert "image_base64" in data

    def test_generate_image_with_purpose(self, client, mock_image_adapter):
        """Test image generation with purpose field."""
        response = client.post(
            "/api/generate-image",
            json={
                "prompt": "UI mockup for dashboard",
                "project_id": "summitflow",
                "purpose": "mockup_generation",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data

    def test_generate_image_with_style(self, client, mock_image_adapter):
        """Test image generation with style parameter."""
        response = client.post(
            "/api/generate-image",
            json={
                "prompt": "A cat",
                "project_id": "test-project",
                "style": "photorealistic",
            },
        )

        assert response.status_code == 200
        # Verify adapter was called with style
        call_kwargs = mock_image_adapter.return_value.generate_image.call_args.kwargs
        assert call_kwargs["style"] == "photorealistic"

    def test_generate_image_missing_project_id(self, client):
        """Test validation error for missing project_id."""
        response = client.post(
            "/api/generate-image",
            json={
                "prompt": "A sunset",
            },
        )

        assert response.status_code == 422

    def test_generate_image_missing_prompt(self, client):
        """Test validation error for missing prompt."""
        response = client.post(
            "/api/generate-image",
            json={
                "project_id": "test-project",
            },
        )

        assert response.status_code == 422

    def test_generate_image_rate_limit_error(self, client):
        """Test rate limit error handling."""
        clear_image_adapter_cache()
        adapter = AsyncMock()
        adapter.generate_image = AsyncMock(side_effect=RateLimitError("gemini", retry_after=30))

        with patch("app.api.image._get_image_adapter", return_value=adapter):
            response = client.post(
                "/api/generate-image",
                json={
                    "prompt": "A sunset",
                    "project_id": "test-project",
                },
            )

            assert response.status_code == 429
            assert "Retry-After" in response.headers

    def test_generate_image_auth_error(self, client):
        """Test authentication error handling."""
        clear_image_adapter_cache()
        adapter = AsyncMock()
        adapter.generate_image = AsyncMock(side_effect=AuthenticationError("gemini"))

        with patch("app.api.image._get_image_adapter", return_value=adapter):
            response = client.post(
                "/api/generate-image",
                json={
                    "prompt": "A sunset",
                    "project_id": "test-project",
                },
            )

            assert response.status_code == 401

    def test_generate_image_provider_error(self, client):
        """Test provider error handling."""
        clear_image_adapter_cache()
        adapter = AsyncMock()
        adapter.generate_image = AsyncMock(
            side_effect=ProviderError("Generation failed", provider="gemini", status_code=503)
        )

        with patch("app.api.image._get_image_adapter", return_value=adapter):
            response = client.post(
                "/api/generate-image",
                json={
                    "prompt": "A sunset",
                    "project_id": "test-project",
                },
            )

            assert response.status_code == 503
