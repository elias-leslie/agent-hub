"""Tests for Cloudflare Workers AI adapters (text + image)."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.adapters.cloudflare import _CLOUDFLARE_MODEL_MAP, CloudflareAdapter
from app.adapters.cloudflare_image import (
    _FALLBACK_CHAIN,
    _MODEL_PATH,
    CloudflareImageAdapter,
)

# ---------------------------------------------------------------------------
# Text adapter tests
# ---------------------------------------------------------------------------


class TestCloudflareAdapter:
    """Test cases for Cloudflare Workers AI text adapter."""

    @patch("app.adapters.cloudflare._resolve_account_id", return_value="test-account-123")
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_provider_name(self, mock_openai: MagicMock, mock_account: MagicMock) -> None:
        adapter = CloudflareAdapter(api_key="test-key")
        assert adapter.provider_name == "cloudflare"

    @patch("app.adapters.cloudflare._resolve_account_id", return_value="test-account-123")
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_base_url_includes_account_id(self, mock_openai: MagicMock, mock_account: MagicMock) -> None:
        CloudflareAdapter(api_key="test-key")
        call_kwargs = mock_openai.call_args[1]
        assert call_kwargs["base_url"] == "https://api.cloudflare.com/client/v4/accounts/test-account-123/ai/v1"

    @patch("app.adapters.cloudflare._resolve_account_id", return_value="test-account-123")
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_model_resolution(self, mock_openai: MagicMock, mock_account: MagicMock) -> None:
        adapter = CloudflareAdapter(api_key="test-key")
        assert adapter._resolve_model("cloudflare/qwen2.5-coder-32b") == "@cf/qwen/qwen2.5-coder-32b-instruct"
        assert adapter._resolve_model("cloudflare/llama-4-scout-17b") == "@cf/meta/llama-4-scout-17b-16e-instruct"
        assert adapter._resolve_model("cloudflare/qwq-32b") == "@cf/qwen/qwq-32b"

    @patch("app.adapters.cloudflare._resolve_account_id", return_value="test-account-123")
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_model_resolution_passthrough(self, mock_openai: MagicMock, mock_account: MagicMock) -> None:
        adapter = CloudflareAdapter(api_key="test-key")
        assert adapter._resolve_model("unknown-model") == "unknown-model"

    def test_no_api_key_error(self) -> None:
        from app.adapters.base import AuthenticationError

        with patch("app.adapters.cloudflare._resolve_account_id", return_value="test-account-123"), \
             pytest.raises(AuthenticationError):
            CloudflareAdapter(api_key="")

    def test_no_account_id_error(self) -> None:
        from app.adapters.base import AuthenticationError

        with patch("app.adapters.cloudflare._resolve_account_id", side_effect=AuthenticationError("cloudflare")), \
             pytest.raises(AuthenticationError):
            CloudflareAdapter(api_key="test-key")

    @pytest.mark.asyncio
    @patch("app.adapters.cloudflare._resolve_account_id", return_value="test-account-123")
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_completion(self, mock_openai_class: MagicMock, mock_account: MagicMock) -> None:
        from app.adapters.base import Message

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello from Cloudflare!"
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].finish_reason = "stop"
        mock_response.model = "@cf/qwen/qwen2.5-coder-32b-instruct"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 8
        mock_response.usage.completion_tokens = 4

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_class.return_value = mock_client

        adapter = CloudflareAdapter(api_key="test-key")
        result = await adapter.complete(
            messages=[Message(role="user", content="Hi")],
            model="cloudflare/qwen2.5-coder-32b",
        )

        assert result.content == "Hello from Cloudflare!"
        assert result.provider == "cloudflare"

    @pytest.mark.asyncio
    @patch("app.adapters.cloudflare._resolve_account_id", return_value="test-account-123")
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    async def test_health_check_uses_models_list(self, mock_openai_class: MagicMock, mock_account: MagicMock) -> None:
        """Health check should use models.list (zero tokens consumed)."""
        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(return_value=[MagicMock()])
        mock_openai_class.return_value = mock_client

        adapter = CloudflareAdapter(api_key="test-key")
        result = await adapter.health_check()

        assert result is True
        mock_client.models.list.assert_called_once()

    def test_model_map_coverage(self) -> None:
        """All registered Cloudflare LLM models should be in the model map."""
        expected_keys = {
            "gemma-4-26b",
            "glm-4.7-flash",
            "gpt-oss-120b",
            "gpt-oss-20b",
            "granite-4.0-h-micro",
            "kimi-k2.5",
            "kimi-k2.6",
            "llama-4-scout-17b",
            "mistral-small-3.1-24b",
            "nemotron-3-120b",
            "qwen2.5-coder-32b",
            "qwen3-30b",
            "qwq-32b",
        }
        assert len(_CLOUDFLARE_MODEL_MAP) == len(expected_keys)
        assert set(_CLOUDFLARE_MODEL_MAP.keys()) == expected_keys
        # All values should start with @cf/
        for value in _CLOUDFLARE_MODEL_MAP.values():
            assert value.startswith("@cf/"), f"Expected @cf/ prefix, got {value}"


# ---------------------------------------------------------------------------
# Image adapter tests
# ---------------------------------------------------------------------------


class TestCloudflareImageAdapter:
    """Test cases for Cloudflare Workers AI image adapter."""

    def test_provider_name(self) -> None:
        adapter = CloudflareImageAdapter()
        assert adapter.provider_name == "cloudflare"

    @pytest.mark.asyncio
    @patch("app.adapters.cloudflare_image._resolve_account_id", return_value="test-account-123")
    @patch("app.adapters.cloudflare_image.resolve_api_key", return_value="test-key")
    async def test_generate_image_json_response(self, mock_key: MagicMock, mock_account: MagicMock) -> None:
        """Should decode base64 image from JSON response."""
        adapter = CloudflareImageAdapter()
        fake_image = b"PNG_FAKE_DATA"
        fake_b64 = base64.b64encode(fake_image).decode()

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.is_success = True
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"result": {"image": fake_b64}}

        with patch("app.adapters.cloudflare_image.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await adapter.generate_image(
                prompt="a cat",
                model="cloudflare/flux-1-schnell",
            )

        assert result.image_data == fake_image
        assert result.mime_type == "image/png"
        assert result.provider == "cloudflare"

    @pytest.mark.asyncio
    @patch("app.adapters.cloudflare_image._resolve_account_id", return_value="test-account-123")
    @patch("app.adapters.cloudflare_image.resolve_api_key", return_value="test-key")
    async def test_reference_image_multipart(self, mock_key: MagicMock, mock_account: MagicMock) -> None:
        """FLUX.2-dev with reference image should use multipart form data."""
        adapter = CloudflareImageAdapter()
        fake_image = b"PNG_FAKE_DATA"
        fake_b64 = base64.b64encode(fake_image).decode()
        ref_image = b"REF_IMAGE_DATA"

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.is_success = True
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"result": {"image": fake_b64}}

        with patch("app.adapters.cloudflare_image.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await adapter.generate_image(
                prompt="a cat with reference",
                model="cloudflare/flux-2-dev",
                reference_image=ref_image,
            )

        assert result.image_data == fake_image
        # Verify multipart was used (files= kwarg)
        call_kwargs = mock_client.post.call_args[1]
        assert "files" in call_kwargs

    @pytest.mark.asyncio
    @patch("app.adapters.cloudflare_image._resolve_account_id", return_value="test-account-123")
    @patch("app.adapters.cloudflare_image.resolve_api_key", return_value="test-key")
    async def test_fallback_on_rate_limit(self, mock_key: MagicMock, mock_account: MagicMock) -> None:
        """Should fall back to next model on rate limit."""

        adapter = CloudflareImageAdapter()
        fake_image = b"PNG_FAKE_DATA"
        fake_b64 = base64.b64encode(fake_image).decode()

        mock_resp_429 = MagicMock(spec=httpx.Response)
        mock_resp_429.is_success = False
        mock_resp_429.status_code = 429
        mock_resp_429.text = "Rate limited"
        mock_resp_429.headers = {"content-type": "application/json"}

        mock_resp_ok = MagicMock(spec=httpx.Response)
        mock_resp_ok.is_success = True
        mock_resp_ok.headers = {"content-type": "application/json"}
        mock_resp_ok.json.return_value = {"result": {"image": fake_b64}}

        with patch("app.adapters.cloudflare_image.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=[mock_resp_429, mock_resp_ok])
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await adapter.generate_image(
                prompt="a cat",
                model="cloudflare/flux-2-dev",
            )

        assert result.image_data == fake_image
        # Should have fallen back
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    @patch("app.adapters.cloudflare_image._resolve_account_id", return_value="test-account-123")
    @patch("app.adapters.cloudflare_image.resolve_api_key", return_value="test-key")
    async def test_auth_error(self, mock_key: MagicMock, mock_account: MagicMock) -> None:
        """401 should raise AuthenticationError."""
        from app.adapters.base import AuthenticationError

        adapter = CloudflareImageAdapter()

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.is_success = False
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"

        with patch("app.adapters.cloudflare_image.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            with pytest.raises(AuthenticationError):
                await adapter.generate_image(prompt="test", model="cloudflare/flux-1-schnell")

    def test_model_path_coverage(self) -> None:
        """All 8 image models should be in the path map."""
        assert len(_MODEL_PATH) == 8
        expected_keys = {
            "flux-2-dev", "flux-1-schnell", "sd-xl-lightning",
            "sd-xl-base", "sd-v1.5-img2img", "dreamshaper-8-lcm",
            "leonardo-phoenix", "leonardo-lucid-origin",
        }
        assert set(_MODEL_PATH.keys()) == expected_keys
        # All values should start with @cf/
        for value in _MODEL_PATH.values():
            assert value.startswith("@cf/"), f"Expected @cf/ prefix, got {value}"

    def test_fallback_chain(self) -> None:
        """Fallback chain should have 3 models in quality order."""
        assert len(_FALLBACK_CHAIN) == 3
        assert _FALLBACK_CHAIN[0] == "cloudflare/flux-2-dev"
        assert _FALLBACK_CHAIN[1] == "cloudflare/flux-1-schnell"
        assert _FALLBACK_CHAIN[2] == "cloudflare/sd-xl-lightning"
