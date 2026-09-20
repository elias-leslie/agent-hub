"""Reconstruct the frozen maintenance qualification packet without model calls.

This is a retained, narrow reconstruction of the ephemeral evaluation script
used on 2026-09-19. It prints the production prompt/schema hashes and the exact
synthetic packets. It intentionally does not initialize credentials or call a
provider. The original inline heredoc was not persisted, so this file is
reconstructed rather than claimed as the historical script byte-for-byte. The
answer-key rubric was supplied in the task requirements but was not materialized
as a standalone file before the calls; the saved answer_key is retrospective.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from app.models.memory_unified import Memory
from app.services.context_maintenance_recovery import RECOVERY_INSTRUCTION, RecoveryDecision
from app.services.memory._review_agent_prompt import REVIEW_SCHEMA, build_memory_review_prompt

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "docs/evaluations/context-review/gemini-3.8-flash-maintenance-qualification-fixture.json"


def digest(value: object) -> str:
    if isinstance(value, str):
        raw = value.encode()
    else:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def memory(row: dict[str, object]) -> Memory:
    memory_type = str(row.get("memory_type", "reference"))
    return Memory(
        id=UUID(str(row["uuid"])), version=1, content=str(row["content"]),
        name=str(row["name"]), summary=None, memory_type=memory_type,
        scope=str(row.get("scope", "global")), scope_id=None, group_id=None,
        source="synthetic-qualification", source_description="sanitized qualification fixture",
        tags=["synthetic", "qualification"], context_kind="reference",
        applicability=dict(row.get("applicability", {})), tier=2 if memory_type != "reference" else 3,
        pinned=False, auto_inject=False, display_order=50, trigger_task_types=[],
        trigger_phases=[], loaded_count=0, referenced_count=0, helpful_count=0,
        harmful_count=0, status="active", review_status="pending", sensitivity_tier="normal",
        token_count=None, metadata_={},
    )


def build_packet() -> dict[str, object]:
    fixture = json.loads(FIXTURE.read_text())
    memories = [memory(row) for row in fixture["regular_memories"]]
    authority = fixture["authority_prompt"]
    regular_prompt = build_memory_review_prompt(
        memories,
        governance_snapshot=fixture["regular_review_context"]["governance_snapshot"],
        memory_index=memories,
        authority_prompts=[SimpleNamespace(
            slug=authority["slug"], prompt_type="mandate", is_global=True,
            content=authority["content"],
        )],
        authority_prompt_assignments=[fixture["regular_review_context"]["authority_prompt_assignment"]],
        computed_tool_capabilities=fixture["regular_review_context"]["computed_tool_capability_block"],
        coverage=fixture["regular_review_context"]["coverage"],
    )
    sources = fixture["recovery_sources"]
    history_id, policy_id = sources[0]["source_id"], sources[1]["source_id"]
    recovery_packet = {
        "workflow": "Synthetic canonical context-maintenance workflow. Assess the retained item against only supplied immutable evidence.",
        "item": {
            "id": "maintenance:synthetic-history", "kind": "stale",
            "summary": "An earlier heuristic marked the dated incident stale because current endpoint status is unknown.",
            "recommendation": "Dismiss an unsupported stale finding while preserving the dated incident and required policy.",
            "detail": {"synthetic": True}, "owner_answer": None,
        },
        "evidence": {
            "sources": sources, "pairs": [[history_id, policy_id]],
            "findings": [{
                "kind": "stale", "source_ids": [history_id, policy_id],
                "passages": {history_id: sources[0]["content"], policy_id: sources[1]["content"]},
                "explanation": "The heuristic inferred current invalidity from missing present-day evidence.",
                "uncertainty": "Current endpoint state is unknown.",
                "remedy": "Assess whether the historical finding is supported.",
            }],
            "placement_warnings": [], "coverage": fixture["recovery_review_context"]["coverage"],
            "mode": "curator", "proposal_only": True,
        },
    }
    recovery_prompt = (
        RECOVERY_INSTRUCTION
        + "\nSchema: " + json.dumps(RecoveryDecision.model_json_schema(), separators=(",", ":"))
        + "\nEvidence: " + json.dumps(recovery_packet, separators=(",", ":"))
    )
    return {
        "fixture": str(FIXTURE),
        "regular": {
            "user_prompt_sha256": digest(regular_prompt),
            "response_schema_sha256": digest(REVIEW_SCHEMA),
            "input": {
                "memories": fixture["regular_memories"],
                "governance_snapshot": fixture["regular_review_context"]["governance_snapshot"],
                "authority_prompt": authority,
                "authority_prompt_assignment": fixture["regular_review_context"]["authority_prompt_assignment"],
                "computed_tool_capability_block": fixture["regular_review_context"]["computed_tool_capability_block"],
                "coverage": fixture["regular_review_context"]["coverage"],
            },
        },
        "recovery": {
            "user_prompt_sha256": digest(recovery_prompt),
            "instruction_sha256": digest(RECOVERY_INSTRUCTION),
            "response_schema_sha256": digest(RecoveryDecision.model_json_schema()),
            "input": recovery_packet,
        },
        "prompt_builder_source_sha256": digest(inspect.getsource(build_memory_review_prompt)),
    }


if __name__ == "__main__":
    print(json.dumps(build_packet(), indent=2, sort_keys=True))
