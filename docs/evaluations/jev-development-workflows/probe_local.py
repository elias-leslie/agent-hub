"""Read-only, no-provider probes for the frozen Jev development case set."""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from app.services import context_screening  # noqa: E402


def unchanged_since(path: str, pinned_revision: str, files: tuple[str, ...]) -> bool:
    return subprocess.run(
        ["git", "diff", "--quiet", pinned_revision, "--", *files], cwd=path, check=False
    ).returncode == 0


def search_probe(name: str) -> dict[str, object]:
    result = json.loads((HERE / f"search-{name}.json").read_text())
    metadata = result["metadata"]
    context = result["prompt_context"]
    symbols = re.findall(r"^- `([^`]+)` .*? in ([^:]+):", context, re.MULTILINE)
    return {
        "query": result["query"],
        "symbols": len(symbols),
        "first_symbol": symbols[0][0] if symbols else None,
        "text_matches": metadata["text_match_count"],
        "missed_identifiers": metadata["missed_identifier_terms"],
        "suppressed_generic_symbols": metadata["suppressed_generic_symbols"],
        "context_tokens_estimate": metadata["final_tokens"],
        "truncated_source_slice": "[... truncated ...]" in context,
    }


def cache_probe() -> dict[str, bool]:
    left = {"source_id": "A", "revision": "1", "title": "Display A", "content": "Require a receipt", "policy": {"format": "full"}, "authority": "project"}
    right = {"source_id": "B", "revision": "1", "title": "Display B", "content": "Keep the receipt", "policy": {"format": "full"}, "authority": "project"}
    context = {"project_id": "agent-hub", "agent_slug": "coder", "consumer_surface": "native"}

    def key(a: dict, b: dict, c: dict, model: str = "jev-1.13.0") -> str:
        return context_screening.screening_identity(a, b, c, model)[0]

    baseline = key(left, right, context)
    reordered = key(right, left, context)
    cosmetic = copy.deepcopy(left)
    cosmetic.update(source_id="renamed", revision="99", title="New display label")
    altered = copy.deepcopy(right)
    altered["content"] = "Do not keep the receipt"
    changed_context = {**context, "project_id": "neri"}
    original_rubric = context_screening.RUBRIC
    try:
        context_screening.RUBRIC = {**original_rubric, "revision": "3"}
        changed_rubric = key(left, right, context)
    finally:
        context_screening.RUBRIC = original_rubric
    return {
        "reordered_same": reordered == baseline,
        "cosmetic_same": key(cosmetic, right, context) == baseline,
        "evidence_change_invalidates": key(left, altered, context) != baseline,
        "candidate_change_invalidates": key(left, {**right, "content": "Different candidate"}, context) != baseline,
        "context_change_invalidates": key(left, right, changed_context) != baseline,
        "rubric_change_invalidates": changed_rubric != baseline,
        "model_change_invalidates": key(left, right, context, "jev-1.14.0") != baseline,
    }


def normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def repeat_probe() -> dict[str, bool]:
    original = "Same task checked 15+ times in heartbeat loop"
    paraphrase = "The same task is polled again and again during each heartbeat"
    first_error = {"error": "HTTP 503", "provider": "gemini", "revision": "A"}
    second_error = {"error": "HTTP 503", "provider": "typesafe", "revision": "B"}
    return {
        "paraphrase_exact_links": original == paraphrase,
        "paraphrase_normalized_links": normalized(original) == normalized(paraphrase),
        "same_error_text_links": normalized(first_error["error"]) == normalized(second_error["error"]),
        "same_error_context_links": first_error == second_error,
    }


def main() -> None:
    cases = json.loads((HERE / "cases-v1.json").read_text())
    assert len(cases["cases"]) == 6
    assert all(case["initial"] and case["holdout"] for case in cases["cases"])
    output = {
        "kind": "local_no_provider_probe",
        "rubric_revision": cases["rubric_revision"],
        "referenced_sources_unchanged": {
            "agent_hub": unchanged_since(str(ROOT), cases["agent_hub_revision"], (
                "backend/app/services/context_screening.py",
                "backend/app/services/typesafe_jev.py",
                "docs/evaluations/context-review/native-runtime-frozen-v1.json",
            )),
            "summitflow": unchanged_since("/srv/workspaces/projects/summitflow", cases["summitflow_revision"], (
                "backend/app/tasks/explorer_tasks.py",
                "frontend/components/layout/ProjectSelector.tsx",
                "docs/st-search-honing.md",
            )),
            "neri": unchanged_since("/srv/workspaces/projects/neri", cases["neri_revision"], (
                "backend/app/st_cli/neri.py",
            )),
        },
        "search": {name: search_probe(name) for name in ("identifier-miss", "mixed", "natural-language")},
        "cache": cache_probe(),
        "repeat": repeat_probe(),
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
