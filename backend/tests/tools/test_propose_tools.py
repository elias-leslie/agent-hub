from __future__ import annotations

import json

from app.services.project_permission_service import _READ_TOOLS
from app.services.tools._propose_tools import (
    execute_propose_committee,
    execute_propose_honing,
    execute_propose_thorough,
)
from app.services.tools.direct_executor_core import DirectToolExecutor
from app.services.tools.tool_definitions import _AGENT_TOOL_REGISTRY


class TestProposeThorough:
    def test_includes_provided_reason(self) -> None:
        out = json.loads(execute_propose_thorough({"reason": "wide cross-source synthesis"}))
        assert out == {
            "recommended": "thorough",
            "reason": "wide cross-source synthesis",
        }

    def test_falls_back_to_default_reason(self) -> None:
        out = json.loads(execute_propose_thorough({}))
        assert out["recommended"] == "thorough"
        assert out["reason"]


class TestProposeCommittee:
    def test_includes_provided_reason(self) -> None:
        out = json.loads(execute_propose_committee({"reason": "contested claim"}))
        assert out == {"recommended": "committee", "reason": "contested claim"}

    def test_falls_back_to_default_reason(self) -> None:
        out = json.loads(execute_propose_committee({}))
        assert out["recommended"] == "committee"
        assert out["reason"]


class TestProposeHoning:
    def test_full_spec_accepted(self) -> None:
        out = json.loads(
            execute_propose_honing(
                {
                    "editable_asset": {
                        "path": "prompts/extractor.md",
                        "kind": "prompt",
                        "current_content": "Extract entities from text.",
                    },
                    "metric": {
                        "kind": "judge",
                        "spec": {"rubric": "Score F1 on a held-out set."},
                    },
                    "hypothesis": "Tighter instruction lifts F1.",
                    "reason": "iterate the extractor",
                }
            )
        )
        assert out["recommended"] == "honing"
        assert out["reason"] == "iterate the extractor"
        assert "declined" not in out
        assert "missing" not in out
        assert out["proposal"]["editable_asset"]["path"] == "prompts/extractor.md"
        assert out["proposal"]["editable_asset"]["kind"] == "prompt"
        assert (
            out["proposal"]["editable_asset"]["current_content_preview"]
            == "Extract entities from text."
        )
        assert out["proposal"]["metric"]["kind"] == "judge"
        assert out["proposal"]["hypothesis"] == "Tighter instruction lifts F1."

    def test_missing_asset_refuses_to_thorough(self) -> None:
        out = json.loads(
            execute_propose_honing(
                {"metric": {"kind": "judge", "spec": {"rubric": "ok"}}}
            )
        )
        assert out["recommended"] == "thorough"
        assert out["declined"] == "honing"
        assert out["missing"] == ["editable_asset"]

    def test_missing_metric_refuses_to_thorough(self) -> None:
        out = json.loads(
            execute_propose_honing(
                {"editable_asset": {"path": "a.md", "kind": "prompt"}}
            )
        )
        assert out["recommended"] == "thorough"
        assert out["declined"] == "honing"
        assert out["missing"] == ["metric"]

    def test_partial_asset_refuses(self) -> None:
        # Missing kind on asset, missing spec on metric.
        out = json.loads(
            execute_propose_honing(
                {
                    "editable_asset": {"path": "a.md"},
                    "metric": {"kind": "harness"},
                }
            )
        )
        assert out["recommended"] == "thorough"
        assert set(out["missing"]) == {"editable_asset", "metric"}

    def test_long_content_is_truncated_to_preview(self) -> None:
        out = json.loads(
            execute_propose_honing(
                {
                    "editable_asset": {
                        "path": "a.md",
                        "kind": "prompt",
                        "current_content": "x" * 500,
                    },
                    "metric": {"kind": "judge", "spec": {"rubric": "ok"}},
                }
            )
        )
        assert len(out["proposal"]["editable_asset"]["current_content_preview"]) == 240


def test_registry_includes_all_three_propose_tools() -> None:
    tools = _AGENT_TOOL_REGISTRY["vantage-research"]
    names = {t.name for t in tools}
    assert "propose_thorough" in names
    assert "propose_committee" in names
    assert "propose_honing" in names


def test_read_tier_includes_propose_tools() -> None:
    # Without this the tier filter would strip them when project permission is `read`.
    for name in ("propose_thorough", "propose_committee", "propose_honing"):
        assert name in _READ_TOOLS


def test_dispatcher_knows_all_three_propose_tools() -> None:
    for name in ("propose_thorough", "propose_committee", "propose_honing"):
        assert name in DirectToolExecutor.DISPATCHABLE_TOOLS
