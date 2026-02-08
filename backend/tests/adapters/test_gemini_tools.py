"""Tests for Gemini tool execution with retry logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import ProviderError
from app.adapters.gemini_tools import _generate_with_retry


class TestGenerateWithRetry:
    """Tests for _generate_with_retry function."""

    @pytest.mark.asyncio
    async def test_generate_success_first_attempt(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        result = await _generate_with_retry(
            client=mock_client,
            model="gemini-3-flash-preview",
            contents=[],
            config=MagicMock(),
        )

        assert result is mock_response
        assert mock_client.aio.models.generate_content.call_count == 1

    @pytest.mark.asyncio
    async def test_generate_retries_on_deadline_exceeded(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock()
        deadline_error = Exception("504 DEADLINE_EXCEEDED. Deadline expired.")
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=[deadline_error, mock_response]
        )

        with patch("app.adapters.gemini_tools.asyncio.sleep", new_callable=AsyncMock):
            result = await _generate_with_retry(
                client=mock_client,
                model="gemini-3-flash-preview",
                contents=[],
                config=MagicMock(),
            )

        assert result is mock_response
        assert mock_client.aio.models.generate_content.call_count == 2

    @pytest.mark.asyncio
    async def test_generate_retries_on_503_provider_error(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock()
        error_503 = ProviderError(
            "Service Unavailable", provider="gemini", status_code=503, retriable=True
        )
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=[error_503, mock_response]
        )

        with patch("app.adapters.gemini_tools.asyncio.sleep", new_callable=AsyncMock):
            result = await _generate_with_retry(
                client=mock_client,
                model="gemini-3-flash-preview",
                contents=[],
                config=MagicMock(),
            )

        assert result is mock_response
        assert mock_client.aio.models.generate_content.call_count == 2

    @pytest.mark.asyncio
    async def test_generate_no_retry_on_auth_error(self) -> None:
        mock_client = MagicMock()
        auth_error = Exception("401 Invalid API key")
        mock_client.aio.models.generate_content = AsyncMock(side_effect=auth_error)

        with pytest.raises(Exception, match="401 Invalid API key"):
            await _generate_with_retry(
                client=mock_client,
                model="gemini-3-flash-preview",
                contents=[],
                config=MagicMock(),
            )

        assert mock_client.aio.models.generate_content.call_count == 1

    @pytest.mark.asyncio
    async def test_generate_exhausts_retries(self) -> None:
        mock_client = MagicMock()
        deadline_error = Exception("504 DEADLINE_EXCEEDED")
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=[deadline_error, deadline_error, deadline_error]
        )

        with (
            patch("app.adapters.gemini_tools.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(Exception, match="DEADLINE_EXCEEDED"),
        ):
            await _generate_with_retry(
                client=mock_client,
                model="gemini-3-flash-preview",
                contents=[],
                config=MagicMock(),
            )

        assert mock_client.aio.models.generate_content.call_count == 3

    @pytest.mark.asyncio
    async def test_generate_retry_exponential_backoff(self) -> None:
        mock_client = MagicMock()
        mock_response = MagicMock()
        deadline_error = Exception("504 DEADLINE_EXCEEDED")
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=[deadline_error, deadline_error, mock_response]
        )

        mock_sleep = AsyncMock()
        with patch("app.adapters.gemini_tools.asyncio.sleep", mock_sleep):
            await _generate_with_retry(
                client=mock_client,
                model="gemini-3-flash-preview",
                contents=[],
                config=MagicMock(),
            )

        assert mock_sleep.call_count == 2
        # First delay: 2.0 * 2^0 = 2.0
        assert mock_sleep.call_args_list[0].args[0] == 2.0
        # Second delay: 2.0 * 2^1 = 4.0
        assert mock_sleep.call_args_list[1].args[0] == 4.0
