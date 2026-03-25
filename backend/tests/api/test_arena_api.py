"""Tests for Arena API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .test_agents_api import make_mock_dto


class TestArenaOverviewEndpoint:
    """Tests for GET /api/arena/overview."""

    @pytest.mark.asyncio
    async def test_get_arena_overview_returns_aggregated_payload(self, api_client) -> None:
        agents = [
            make_mock_dto(slug="persona", name="Jenny"),
            make_mock_dto(id=2, slug="debugger", name="Debugger"),
        ]
        payload = {
            "generated_at": "2026-03-22T15:30:00Z",
            "project_id": "agent-hub",
            "primary_agent_slug": "persona",
            "days": 30,
            "system": {
                "total_agents": 2,
                "agents_with_history": 1,
                "total_runs": 12,
                "avg_score": 91.2,
                "avg_pass_rate": 77.0,
                "total_regressions": 3,
                "regressions_by_category": {"behavior": 3},
            },
            "scheduled_jobs": [
                {
                    "id": "job-1",
                    "name": "Daily Jenny Improvement Review",
                    "payload_type": "agent_turn",
                    "enabled": True,
                    "last_run_at": None,
                    "next_run_at": "2026-03-23T09:00:00Z",
                    "run_count": 0,
                }
            ],
            "agent_signal_volume": [
                {
                    "agent_slug": "persona",
                    "friction": 2,
                    "improvement": 1,
                    "idea": 0,
                    "praise": 0,
                    "system": 2,
                }
            ],
            "repeated_issues": [
                {
                    "agent_slug": "persona",
                    "feedback_type": "friction",
                    "content": "missed rebuild.sh before verification",
                    "count": 2,
                    "latest_at": "2026-03-22T09:30:00Z",
                }
            ],
            "recent_benchmark_experiments": [
                {
                    "suite_id": "persona-suite",
                    "decision": "hold",
                    "decision_reason": "underpowered",
                    "score_delta": -0.5,
                    "pass_rate_delta": 0.0,
                }
            ],
            "open_regression_clusters": [
                {
                    "case_id": "rebuild_rule_reconsideration",
                    "occurrence_count": 3,
                    "failure_detail": "forgot rebuild.sh",
                    "failure_category": "behavior",
                    "last_seen_at": "2026-03-22T09:30:00Z",
                }
            ],
            "memory_utilization": {
                "injection_sessions": 4,
                "citation_sessions": 2,
                "lookup_after_injection_sessions": 2,
                "citation_session_rate": 0.5,
                "assistant_citation_rate": 0.5,
                "selected_reference_citation_rate": 0.333,
                "memory_search_calls": 5,
                "memory_get_calls": 1,
                "memory_debug_coverage_rate": 1.0,
            },
            "memory_governance": {
                "active_count": 18,
                "by_context_kind": {"policy": 7, "reference": 11},
                "targeted_count": 4,
                "explicit_exclusion_count": 1,
                "untargeted_reference_count": 7,
                "policy_with_targeting_count": 0,
                "missing_reference_summary_count": 2,
                "missing_capability_summary_count": 0,
                "oversized_policy_count": 1,
                "alias_trigger_task_type_count": 1,
                "invalid_trigger_task_type_count": 0,
                "invalid_trigger_task_type_samples": [],
                "issue_count": 3,
            },
            "low_yield_references": [
                {
                    "uuid": "ref-2",
                    "label": "noisy-ref",
                    "selected": 2,
                    "cited": 0,
                    "citation_rate": 0.0,
                    "tags": ["debugger-relevant"],
                }
            ],
            "agents": [
                {
                    "slug": "persona",
                    "name": "Jenny",
                    "description": "Primary persona",
                    "benchmark": {
                        "total_runs": 12,
                        "avg_score": 91.2,
                        "pass_rate": 77.0,
                        "open_regressions": 3,
                        "latest_completed_at": "2026-03-22T12:00:00Z",
                    },
                    "signal_volume": {
                        "agent_slug": "persona",
                        "friction": 2,
                        "improvement": 1,
                        "idea": 0,
                        "praise": 0,
                        "system": 2,
                    },
                    "top_issue": {
                        "agent_slug": "persona",
                        "feedback_type": "friction",
                        "content": "missed rebuild.sh before verification",
                        "count": 2,
                        "latest_at": "2026-03-22T09:30:00Z",
                    },
                }
            ],
        }

        with (
            patch("app.api.arena.get_agent_service") as mock_get_service,
            patch("app.api.arena.get_arena_overview", new=AsyncMock(return_value=payload)) as mock_get_overview,
        ):
            mock_svc = MagicMock()
            mock_svc.list_agents = AsyncMock(return_value=agents)
            mock_get_service.return_value = mock_svc

            response = api_client.get("/api/arena/overview?days=30&project_id=agent-hub")

            assert response.status_code == 200
            data = response.json()
            assert data["system"]["total_agents"] == 2
            assert data["scheduled_jobs"][0]["name"] == "Daily Jenny Improvement Review"
            assert data["agents"][0]["slug"] == "persona"
            mock_get_overview.assert_awaited_once()
