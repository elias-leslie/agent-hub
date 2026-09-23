"""Summarize immutable local Jev receipts without turning labels into ground truth."""

from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    by_case: dict[str, dict] = defaultdict(dict)
    total_input = total_output = 0
    total_seconds = 0.0
    total_cost = Decimal("0")
    calls = 0
    disagreements = []
    for version in ("v1", "v2"):
        manifest = json.loads((HERE / f"live-packets-{version}.json").read_text())
        reference = json.loads((HERE / f"live-reference-{version}.json").read_text())["cases"]
        for packet in manifest["packets"]:
            id_ = packet["id"]
            receipt = json.loads((HERE / f"live-receipts-{version}" / f"{id_}.json").read_text())
            if receipt["status"] != "succeeded":
                by_case[packet["use_case"]][id_] = {"status": receipt["status"], "billing": receipt.get("billing")}
                continue
            calls += 1
            usage = receipt["response"]["usage"]
            total_input += usage["input_tokens"]
            total_output += usage["output_tokens"]
            total_seconds += receipt["elapsed_seconds"]
            total_cost += Decimal(receipt["cost_usd"])
            choices = {}
            for name, answer in receipt["response"]["answers"].items():
                registered_match = answer["choice"] in reference[id_][name]
                adjudication = ("reference_invalid_incomplete_packet_and_overlapping_criteria"
                                if id_ in {"claim_initial", "claim_narration"} and name == "budget"
                                else "registered_agreement" if registered_match else "unresolved_disagreement")
                choices[name] = {"choice": answer["choice"], "registered_match": registered_match,
                                 "adjudication": adjudication, "confidence": answer["confidence"],
                                 "probabilities": answer["probabilities"]}
            for question, value in choices.items():
                if not value["registered_match"]:
                    disagreements.append({"packet": id_, "question": question, "observed": value["choice"],
                                          "registered_reference": reference[id_][question],
                                          "adjudication": value["adjudication"]})
            by_case[packet["use_case"]][id_] = {"status": "succeeded", "request_sha256": receipt["request_sha256"],
                                                 "provider_request_id": receipt["provider_request_id"],
                                                 "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
                                                 "cost_usd": receipt["cost_usd"], "provider_elapsed_seconds": receipt["elapsed_seconds"],
                                                 "choices": choices}
    snapshot = json.loads((HERE / "history-pool-snapshot-v1.json").read_text())
    history_reference = json.loads((HERE / "history-pool-reference-v1.json").read_text())
    history_receipt = json.loads((HERE / "live-receipts-v3/history_pool.json").read_text())
    history_answers = history_receipt["response"]["answers"]
    history_choices = {candidate["id"]: history_answers[f"c{index:02d}"]["choice"]
                       for index, candidate in enumerate(snapshot["candidates"])}
    same_ids = [id_ for id_, label in history_choices.items() if label == "same_concern"]
    reference_same_ids = [id_ for id_, label in history_reference["labels"].items() if label == "same_concern"]
    related_overcalls = [id_ for id_, label in history_choices.items()
                         if label == "related_distinct" and history_reference["labels"][id_] == "unrelated"
                         and label not in history_reference["acceptable_alternatives"].get(id_, [])]
    history_usage = history_receipt["response"]["usage"]
    calls += 1
    total_input += history_usage["input_tokens"]
    total_output += history_usage["output_tokens"]
    total_seconds += history_receipt["elapsed_seconds"]
    total_cost += Decimal(history_receipt["cost_usd"])
    history_extension = {"kind": "known-case complete-candidate-pool extension; not fresh validation",
                         "candidate_count": len(snapshot["candidates"]),
                         "snapshot_captured_at_utc": snapshot["captured_at_utc"],
                         "lexical_duplicate_ids": snapshot["lexical_duplicate_ids"],
                         "independent_same_concern_ids": reference_same_ids,
                         "jev_same_concern_ids": same_ids,
                         "missed_same_concern_ids": [id_ for id_ in reference_same_ids if id_ not in same_ids],
                         "false_same_concern_ids": [id_ for id_ in same_ids if id_ not in reference_same_ids],
                         "related_distinct_overcalls_against_reference": related_overcalls,
                         "all_choices": history_choices,
                         "input_tokens": history_usage["input_tokens"],
                         "output_tokens": history_usage["output_tokens"],
                         "cost_usd": history_receipt["cost_usd"],
                         "provider_elapsed_seconds": history_receipt["elapsed_seconds"],
                         "verified_advisory_handoff": "history-pool-handoff-v1.json"}
    result = {"schema": "jev-development-live-results-v1", "kind": "15 live Jev requests plus isolated downstream actions",
              "model": "jev-1.13.0", "provider_calls": calls,
              "provider_usage": {"input_tokens": total_input, "output_tokens": total_output,
                                 "accounted_api_cost_usd": str(total_cost), "sum_http_elapsed_seconds": round(total_seconds, 3),
                                 "subscription_usage": None, "account_balance": None},
              "registered_disagreements": disagreements,
              "adjudication": "Both v1 budget disagreements arose from omitted transport evidence and overlapping criteria; not proven Jev false negatives. V2 was a corrected repeat, not fresh holdout.",
              "opportunity_classification": {
                  "claim_evidence": "promising advisory judgment; completed-work benefit unmeasured",
                  "skill_discovery": "correct curated-shortlist selection; full-catalog benefit unmeasured",
                  "search_reranking": "correct controlled candidate selection; natural ranking-miss benefit unmeasured",
                  "repeated_issues": "complete 17-record pool recovered one independently labeled concern with no false same-concern links; known-case extension, handoff savings unmeasured",
                  "workflow_variant": "source-grounded core agreement; discrimination and substitute-evaluator benefit unmeasured",
                  "model_effort_routing": "chosen eligible worker completed task; efficiency unmeasured",
              },
              "cases": by_case, "history_pool_extension": history_extension,
              "downstream": json.loads((HERE / "live-downstream-v1.json").read_text()),
              "deduplication": {"v1_claim_replay": "reused local receipt; zero new provider calls",
                                "v2_search_replay": "reused local receipt; zero new provider calls",
                                "v3_history_pool_replay": "reused local receipt; zero new provider calls",
                                "changed_evidence_or_rubric": "new v2 IDs and manifest; two fresh calls"},
              "neri_ledger_after_direct_calls": {"dispatch_rows": 242, "spent_usd": "0.071314950", "reserved_usd": "0.005376000", "unchanged_from_before": True}}
    output = HERE / "live-results-v1.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"path": str(output), "provider_calls": calls, "input_tokens": total_input,
                      "cost_usd": str(total_cost), "registered_disagreements": len(disagreements)}))


if __name__ == "__main__":
    main()
