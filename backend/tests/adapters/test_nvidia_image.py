"""Tests for NVIDIA image generation adapter."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.adapters.nvidia_image import NvidiaImageAdapter
from app.constants.models import NVIDIA_FLUX_1_DEV, NVIDIA_FLUX_1_KONTEXT


class TestNvidiaImageAdapter:
    """Coverage for model-specific NVIDIA image request payloads."""

    @pytest.mark.asyncio
    @patch("app.adapters.nvidia_image.resolve_api_key", return_value="test-key")
    async def test_kontext_uses_raw_base64_reference(
        self,
        mock_key: MagicMock,
    ) -> None:
        """Kontext should receive raw base64, not a data URI wrapper."""
        adapter = NvidiaImageAdapter()
        fake_image = b"JPEG_FAKE_DATA"
        fake_b64 = base64.b64encode(fake_image).decode()
        ref_image = b"REF_IMAGE_DATA"

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "artifacts": [{"base64": fake_b64, "finishReason": "SUCCESS", "seed": 0}]
        }

        with patch("app.adapters.nvidia_image.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await adapter.generate_image(
                prompt="same sprite in a new pose",
                model=NVIDIA_FLUX_1_KONTEXT,
                reference_image=ref_image,
            )

        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["image"] == base64.b64encode(ref_image).decode()

    @pytest.mark.asyncio
    @patch("app.adapters.nvidia_image.resolve_api_key", return_value="test-key")
    async def test_flux_dev_uses_data_uri_reference(
        self,
        mock_key: MagicMock,
    ) -> None:
        """Flux dev img2img should continue sending a data URI."""
        adapter = NvidiaImageAdapter()
        fake_image = b"JPEG_FAKE_DATA"
        fake_b64 = base64.b64encode(fake_image).decode()
        ref_image = b"REF_IMAGE_DATA"

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "artifacts": [{"base64": fake_b64, "finishReason": "SUCCESS", "seed": 0}]
        }

        with patch("app.adapters.nvidia_image.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await adapter.generate_image(
                prompt="same sprite in a new pose",
                model=NVIDIA_FLUX_1_DEV,
                reference_image=ref_image,
                reference_mime_type="image/png",
            )

        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["image"].startswith("data:image/png;base64,")
