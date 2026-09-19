"""Freeze, evaluate and replay the context-screening holdout through its real ledger.

Run with -m scripts.evaluate_context_review --model <catalog-id> [--execute].
Default is a read-only estimate. This never uses the Neri pilot budget.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from app.db import async_session
from app.services.context_governance import record
from app.services.context_policy import ContextPolicy, semantic_hash
from app.services.context_review import ContextReviewRequest
from app.services.context_screening import RUBRIC, screen_pairs
from app.services.runtime_context import CanonicalContextDeliveryRequest

ROOT = Path(__file__).resolve().parents[1]


async def evaluate(model: str, execute: bool, output: Path) -> None:
    fixture = json.loads(await asyncio.to_thread((ROOT / "tests/fixtures/context_review/heldout-v1.json").read_text))
    expected = json.loads(await asyncio.to_thread((ROOT / "tests/fixtures/context_review/heldout-v1.answers.json").read_text))
    context = CanonicalContextDeliveryRequest(consumer_surface="codex", project_id="agent-hub")
    sources, pairs = [], []
    for case in fixture["cases"]:
        pair = []
        for side in ("left", "right"):
            source_id = f"qualification:{case['id']}:{side}"
            sources.append({"source_type": "fixture", "source_id": source_id, "revision": semantic_hash(case[side]),
                "content": case[side], "authority": "operator_instruction",
                "policy": ContextPolicy(scope="global").model_dump()})
            pair.append(source_id)
        pairs.append(pair)
    prepared = {"sources": sources, "pairs": pairs, "findings": [], "coverage": {
        "context": context.model_dump(mode="json"), "method": fixture["method"], "candidate_pairs": len(pairs)}}
    request = ContextReviewRequest(context=context, mode="jev", dry_run=not execute, model_id=model)
    async with async_session() as db:
        registration = None
        if execute:
            registration = await record(db, "evaluation_registration", "context-evaluation", {
                "fixture_sha256": semantic_hash(fixture), "answer_key_sha256": semantic_hash(expected),
                "rubric_sha256": semantic_hash(RUBRIC), "model": model, "cases": fixture,
                "qualification": "Evidence only; no automatic default activation",
            })
            await db.commit()
        start = time.monotonic()
        result = await screen_pairs(db, dict(prepared), request, "context-evaluation")
        elapsed = time.monotonic() - start
        if "screening" not in result:
            raise RuntimeError(result["reason"])
        outcomes = []
        for case, entry in zip(fixture["cases"], result["screening"]["entries"], strict=True):
            response = entry.get("result") or {}
            choice = response.get("deterministic_relationship") or response.get("answers", {}).get("relationship", {}).get("choice")
            outcomes.append({"case": case["id"], "expected": expected[case["id"]], "actual": choice,
                "matches": choice == expected[case["id"]], "status": entry["status"], "response": response})
        replay = None
        if execute:
            replay = await screen_pairs(db, dict(prepared), request.model_copy(update={"dry_run": True}), "context-evaluation")
        evidence = {"registration": registration, "fixture_sha256": semantic_hash(fixture), "model": model,
            "rubric": RUBRIC, "elapsed_seconds": elapsed, "screening": result["screening"], "outcomes": outcomes,
            "matches": sum(outcome["matches"] for outcome in outcomes), "total": len(outcomes),
            "cache_replay": replay["screening"] if replay else None,
            "qualification": "Synthetic developer-labelled holdout; not independent production qualification. Jev remains opt-in.",
            "native_task_success": "not measured by this pair-judgment evaluation"}
        if execute:
            evidence["record_id"] = await record(db, "evaluation_result", "context-evaluation", evidence)
            await db.commit()
        await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(output.write_text, json.dumps(evidence, indent=2) + "\n")
        print(json.dumps({"file": str(output), "execute": execute, "matches": evidence["matches"], "total": evidence["total"],
            "new_calls": result["screening"]["new_calls"], "cost_usd": result["screening"].get("actual_new_cost_usd"),
            "replay_new_calls": replay["screening"]["new_calls"] if replay else None}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(evaluate(args.model, args.execute, args.output))
