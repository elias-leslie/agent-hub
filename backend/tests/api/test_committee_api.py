"""Tests for the committee roundtable API endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCommitteeAPI:
    @pytest.mark.asyncio
    async def test_committee_roundtable_returns_structured_response(self, api_client) -> None:
        payload = {
            "agent_slug": "investment-committee",
            "committee_config": {
                "orchestrator": {
                    "agent_slug": "investment-committee",
                    "model_id": "codex/gpt-5.4",
                },
                "seats": [
                    {
                        "key": "macro",
                        "label": "Macro",
                        "enabled": True,
                        "agent_slug": "market-pulse-analyst",
                        "model_id": "codex/gpt-5.4",
                        "instruction": "Focus on macro regime.",
                        "weight": 1.0,
                    }
                ],
            },
            "committee_summary": {"headline": "Constructive risk appetite"},
            "calls": [
                {
                    "symbol": "SPY",
                    "window_days": 3,
                    "direction_label": "bullish",
                    "prob_up": 0.64,
                    "expected_move_pct": 1.8,
                    "confidence_score": 78,
                }
            ],
            "votes": [
                {
                    "seat_key": "macro",
                    "agent_slug": "market-pulse-analyst",
                    "model_id": "codex/gpt-5.4",
                    "provider": "codex",
                    "symbol": "SPY",
                    "window_days": 3,
                    "direction_label": "bullish",
                    "prob_up": 0.66,
                    "expected_move_pct": 2.0,
                    "confidence_score": 81,
                }
            ],
        }

        with patch("app.api.endpoints.committee.CommitteeRoundtableService") as mock_service_cls:
            mock_service = MagicMock()
            mock_service.run_roundtable = AsyncMock(return_value=payload)
            mock_service_cls.return_value = mock_service

            response = api_client.post(
                "/api/orchestration/committee",
                json={
                    "prompt": "Forecast SPY and sectors.",
                    "window_days": 3,
                    "source_snapshot": {"clusters": {}},
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["agent_slug"] == "investment-committee"
        assert data["committee_summary"]["headline"] == "Constructive risk appetite"
        assert data["calls"][0]["symbol"] == "SPY"
        call_args = mock_service.run_roundtable.await_args
        assert call_args is not None
        assert call_args.args[0].agent_slug == "investment-committee"
