"""Tests for LLM Model Registry API."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    """Async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


class TestListModels:
    """Tests for GET /api/models endpoint."""

    @pytest.mark.asyncio
    async def test_list_models_returns_200(self, client: AsyncClient):
        """List models returns 200 OK with models."""
        response = await client.get("/api/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert "count" in data
        assert data["count"] > 0

    @pytest.mark.asyncio
    async def test_list_models_returns_expected_fields(self, client: AsyncClient):
        """Models have required fields."""
        response = await client.get("/api/models")
        data = response.json()

        for model in data["models"]:
            assert "id" in model
            assert "display_name" in model
            assert "provider" in model
            assert "context_window" in model
            assert "capabilities" in model
            assert "is_active" in model
            assert "is_deprecated" in model

    @pytest.mark.asyncio
    async def test_list_models_includes_claude(self, client: AsyncClient):
        """List includes Claude models."""
        response = await client.get("/api/models")
        data = response.json()

        claude_models = [m for m in data["models"] if m["provider"] == "anthropic"]
        assert len(claude_models) >= 3  # sonnet, opus, haiku

    @pytest.mark.asyncio
    async def test_list_models_includes_gemini(self, client: AsyncClient):
        """List includes Gemini models."""
        response = await client.get("/api/models")
        data = response.json()

        gemini_models = [m for m in data["models"] if m["provider"] == "google"]
        assert len(gemini_models) >= 2  # flash, pro

    @pytest.mark.asyncio
    async def test_filter_by_provider(self, client: AsyncClient):
        """Filter by provider returns only matching models."""
        response = await client.get("/api/models?provider=anthropic")
        data = response.json()

        for model in data["models"]:
            assert model["provider"] == "anthropic"

    @pytest.mark.asyncio
    async def test_filter_by_provider_google(self, client: AsyncClient):
        """Filter by google provider."""
        response = await client.get("/api/models?provider=google")
        data = response.json()

        for model in data["models"]:
            assert model["provider"] == "google"


class TestGetModel:
    """Tests for GET /api/models/{model_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_model_returns_200(self, client: AsyncClient):
        """Get specific model returns 200 OK."""
        response = await client.get("/api/models/claude-sonnet-4-5")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "claude-sonnet-4-5"
        assert data["provider"] == "anthropic"

    @pytest.mark.asyncio
    async def test_get_model_returns_all_fields(self, client: AsyncClient):
        """Model response includes all fields."""
        response = await client.get("/api/models/claude-sonnet-4-5")
        data = response.json()

        assert data["display_name"] == "Claude Sonnet 4.5"
        assert data["context_window"] == 200000
        assert data["max_output_tokens"] == 64000
        assert data["input_price_per_m"] is not None
        assert data["output_price_per_m"] is not None
        assert "vision" in data["capabilities"]

    @pytest.mark.asyncio
    async def test_get_gemini_model(self, client: AsyncClient):
        """Get Gemini model works."""
        response = await client.get("/api/models/gemini-3-flash-preview")
        assert response.status_code == 200
        data = response.json()
        assert data["provider"] == "google"
        assert data["context_window"] == 1000000

    @pytest.mark.asyncio
    async def test_get_nonexistent_model_returns_404(self, client: AsyncClient):
        """Get nonexistent model returns 404."""
        response = await client.get("/api/models/nonexistent-model")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()


class TestModelCapabilities:
    """Tests for model capabilities."""

    @pytest.mark.asyncio
    async def test_claude_models_have_vision(self, client: AsyncClient):
        """Claude models support vision."""
        response = await client.get("/api/models/claude-sonnet-4-5")
        data = response.json()
        assert data["capabilities"].get("vision") is True

    @pytest.mark.asyncio
    async def test_claude_models_have_function_calling(self, client: AsyncClient):
        """Claude models support function calling."""
        response = await client.get("/api/models/claude-sonnet-4-5")
        data = response.json()
        assert data["capabilities"].get("function_calling") is True

    @pytest.mark.asyncio
    async def test_gemini_image_model_has_image_gen(self, client: AsyncClient):
        """Gemini image model supports image generation."""
        response = await client.get("/api/models/gemini-3-pro-image-preview")
        data = response.json()
        assert data["capabilities"].get("image_gen") is True
