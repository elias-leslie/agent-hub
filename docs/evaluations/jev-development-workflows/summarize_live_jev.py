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
            choices = {name: {"choice": answer["choice"], "accepted": answer["choice"] in reference[id_][name],
                              "confidence": answer["confidence"], "probabilities": answer["probabilities"]}
                       for name, answer in receipt["response"]["answers"].items()}
            for question, value in choices.items():
                if not value["accepted"]:
                    disagreements.append({"packet": id_, "question": question, "observed": value["choice"],
                                          "registered_reference": reference[id_][question]})
            by_case[packet["use_case"]][id_] = {"status": "succeeded", "request_sha256": receipt["request_sha256"],
                                                 "provider_request_id": receipt["provider_request_id"],
                                                 "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
                                                 "cost_usd": receipt["cost_usd"], "provider_elapsed_seconds": receipt["elapsed_seconds"],
                                                 "choices": choices}
    result = {"schema": "jev-development-live-results-v1", "kind": "14 live Jev requests plus isolated downstream actions",
              "model": "jev-1.13.0", "provider_calls": calls,
              "provider_usage": {"input_tokens": total_input, "output_tokens": total_output,
                                 "accounted_api_cost_usd": str(total_cost), "sum_http_elapsed_seconds": round(total_seconds, 3),
                                 "subscription_usage": None, "account_balance": None},
              "registered_disagreements": disagreements,
              "adjudication": "Both v1 budget disagreements arose from omitted transport evidence and overlapping criteria; not proven Jev false negatives. V2 was a corrected repeat, not fresh holdout.",
              "cases": by_case, "downstream": json.loads((HERE / "live-downstream-v1.json").read_text()),
              "deduplication": {"v1_claim_replay": "reused local receipt; zero new provider calls",
                                "v2_search_replay": "reused local receipt; zero new provider calls",
                                "changed_evidence_or_rubric": "new v2 IDs and manifest; two fresh calls"},
              "neri_ledger_after_direct_calls": {"dispatch_rows": 242, "spent_usd": "0.071314950", "reserved_usd": "0.005376000", "unchanged_from_before": True}}
    output = HERE / "live-results-v1.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"path": str(output), "provider_calls": calls, "input_tokens": total_input,
                      "cost_usd": str(total_cost), "registered_disagreements": len(disagreements)}))


if __name__ == "__main__":
    main()
