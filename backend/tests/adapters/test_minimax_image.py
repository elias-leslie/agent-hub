"""Tests for MiniMax image generation adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.adapters.base import ProviderError
from app.adapters.minimax_image import MinimaxImageAdapter


class TestMinimaxImageAdapter:
    """Adapter behavior specific to MiniMax image generation."""

    @patch("app.adapters.minimax_image.resolve_api_key", return_value="sk-cp-test-coding-plan")
    def test_rejects_coding_plan_api_keys(self, mock_key: MagicMock) -> None:
        """Coding-plan keys should fail fast with a clear image API error."""
        adapter = MinimaxImageAdapter()

        with pytest.raises(ProviderError, match="coding-plan API keys are not valid"):
            adapter._api_key()
