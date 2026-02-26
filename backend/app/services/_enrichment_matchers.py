"""Matching logic: map catalog model IDs to external data source entries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services._enrichment_normalizers import (
    LIVEBENCH_IF_TASKS,
    LIVEBENCH_REASONING_TASKS,
    _bare_model_id,
    _livebench_avg,
    _livebench_category_avg,
    _normalize_arimxyer_index,
    _normalize_bfcl_name,
    _normalize_livebench_name,
    _parse_pct,
    _parse_price,
)

if TYPE_CHECKING:
    from app.constants.catalog import ModelEntry


def _find_in_models_dev(
    bare_id: str, models_dev_data: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find a models.dev entry by exact ``id`` match against bare model ID."""
    for entry in models_dev_data:
        ext_id = entry.get("id", "")
        if ext_id and bare_id == ext_id:
            return entry
    return None


def _find_in_benchmarks(
    bare_id: str, family: str | None, benchmark_data: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find a benchmark entry by ``slug`` match.

    Tries exact match, then strips ``-preview`` suffix, then family-prefix
    match (best scorer by intelligence_index).
    """
    for entry in benchmark_data:
        slug = entry.get("slug", "")
        if slug and bare_id == slug:
            return entry

    stripped = bare_id.removesuffix("-preview")
    if stripped != bare_id:
        for entry in benchmark_data:
            slug = entry.get("slug", "")
            if slug and stripped == slug:
                return entry

    if family:
        return _find_benchmark_by_family(family, benchmark_data)

    return None


def _find_benchmark_by_family(
    family: str, benchmark_data: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find best benchmark entry matching by family name parts."""
    family_prefix = family.replace("_", "-")
    family_parts = set(family_prefix.split("-"))
    family_matches = [
        entry for entry in benchmark_data
        if family_parts.issubset(set(entry.get("slug", "").split("-")))
        and "reasoning" not in entry.get("slug", "")
    ]
    if not family_matches:
        return None
    return max(family_matches, key=lambda e: float(e.get("intelligence_index", 0) or 0))


def _find_in_bfcl(
    bare_id: str, family: str | None, bfcl_data: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find a BFCL entry by normalized name match.

    Prefers (FC) entries over (Prompt) entries. Tries exact match on normalized
    name first, then family-prefix match (best scorer).
    """
    candidates = [
        (norm, orig, row)
        for row in bfcl_data
        if (orig := row.get("Model", "").strip())
        for norm in [_normalize_bfcl_name(orig)]
    ]

    bare_stripped = bare_id.removesuffix("-preview")
    exact_matches = [
        (orig, row) for norm, orig, row in candidates
        if norm in (bare_id, bare_stripped)
    ]
    if exact_matches:
        for orig, row in exact_matches:
            if "(FC)" in orig and "thinking" not in orig.lower():
                return row
        return exact_matches[0][1]

    if family:
        return _find_bfcl_by_family(family, candidates)

    return None


def _find_bfcl_by_family(
    family: str,
    candidates: list[tuple[str, str, dict[str, Any]]],
) -> dict[str, Any] | None:
    """Find best BFCL entry for a given model family."""
    prefix = family.replace("_", "-")
    family_matches = [
        (orig, row) for norm, orig, row in candidates
        if norm.startswith(prefix)
    ]
    if not family_matches:
        return None
    fc_matches = [
        (o, r) for o, r in family_matches
        if "(FC)" in o and "thinking" not in o.lower()
    ]
    pool = fc_matches or family_matches
    best = max(pool, key=lambda x: _parse_pct(x[1].get("Overall Acc", "0")))
    return best[1]


def _find_in_livebench(
    bare_id: str, family: str | None, livebench_data: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find a LiveBench entry by normalized name match.

    Tries exact match, then family match (best overall scorer).
    """
    candidates = [
        (_normalize_livebench_name(row.get("model", "").strip()), row)
        for row in livebench_data
        if row.get("model", "").strip()
    ]

    bare_stripped = bare_id.removesuffix("-preview")
    exact = [row for norm, row in candidates if norm in (bare_id, bare_stripped)]
    if exact:
        return max(exact, key=lambda r: _livebench_avg(r, list(r.keys())))

    if family:
        prefix = family.replace("_", "-")
        family_matches = [row for norm, row in candidates if norm.startswith(prefix)]
        if family_matches:
            return max(family_matches, key=lambda r: _livebench_avg(r, list(r.keys())))

    return None


def _extract_models_dev_fields(
    dev_entry: dict[str, Any],
) -> dict[str, Any]:
    """Extract pricing and speed fields from a models.dev entry."""
    enrichment: dict[str, Any] = {}
    cost = dev_entry.get("cost", {})
    if cost:
        if "input" in cost:
            enrichment["ext_input_per_m"] = _parse_price(cost["input"])
        if "output" in cost:
            enrichment["ext_output_per_m"] = _parse_price(cost["output"])
    tps = dev_entry.get("output_tps")
    if tps:
        if tps >= 100:
            enrichment["ext_speed_tier"] = "fast"
        elif tps >= 40:
            enrichment["ext_speed_tier"] = "medium"
        else:
            enrichment["ext_speed_tier"] = "slow"
    return enrichment


def _extract_benchmark_fields(
    bench_entry: dict[str, Any],
) -> dict[str, Any]:
    """Extract coding and reasoning fields from an arimxyer benchmark entry."""
    enrichment: dict[str, Any] = {}
    if bench_entry.get("intelligence_index"):
        enrichment["ext_reasoning"] = _normalize_arimxyer_index(
            bench_entry["intelligence_index"]
        )
    coding_score = (
        bench_entry.get("coding_index")
        or bench_entry.get("humaneval")
        or bench_entry.get("swe_bench")
    )
    if coding_score:
        enrichment["ext_coding"] = _normalize_arimxyer_index(coding_score)
    return enrichment


def _compute_instruction_score(
    bench_entry: dict[str, Any] | None,
    lb_entry: dict[str, Any] | None,
) -> int | None:
    """Blend arimxyer ifbench and LiveBench IF avg into an instruction score."""
    arimxyer_if = None
    if bench_entry and bench_entry.get("ifbench"):
        try:
            v = float(bench_entry["ifbench"])
            arimxyer_if = min(100, round(v * 100)) if v <= 1.0 else min(100, round(v))
        except (ValueError, TypeError):
            pass

    lb_if = None
    if lb_entry:
        lb_if_avg = _livebench_category_avg(lb_entry, LIVEBENCH_IF_TASKS)
        if lb_if_avg is not None and lb_if_avg > 0:
            lb_if = min(100, round(lb_if_avg))

    if arimxyer_if is not None and lb_if is not None:
        return round((arimxyer_if + lb_if) / 2)
    if arimxyer_if is not None:
        return arimxyer_if
    if lb_if is not None:
        return lb_if
    return None


def _apply_bfcl(
    bare_id: str,
    family: str | None,
    bfcl_data: list[dict[str, Any]],
    enrichment: dict[str, Any],
    raw: dict[str, Any],
) -> None:
    """Match and apply BFCL tool-use score into enrichment/raw dicts."""
    bfcl_entry = _find_in_bfcl(bare_id, family, bfcl_data)
    if not bfcl_entry:
        return
    raw["bfcl"] = {
        "model": bfcl_entry.get("Model"),
        "overall_acc": bfcl_entry.get("Overall Acc"),
        "rank": bfcl_entry.get("Rank"),
    }
    overall_acc = _parse_pct(bfcl_entry.get("Overall Acc", "0"))
    if overall_acc > 0:
        enrichment["ext_tool_use"] = min(100, round(overall_acc))


def _apply_livebench(
    bare_id: str,
    family: str | None,
    livebench_data: list[dict[str, Any]],
    enrichment: dict[str, Any],
    raw: dict[str, Any],
) -> dict[str, Any] | None:
    """Match and apply LiveBench planning score; return the matched entry."""
    lb_entry = _find_in_livebench(bare_id, family, livebench_data)
    if not lb_entry:
        return None
    raw["livebench"] = {"model": lb_entry.get("model")}
    reasoning_avg = _livebench_category_avg(lb_entry, LIVEBENCH_REASONING_TASKS)
    if reasoning_avg is not None and reasoning_avg > 0:
        enrichment["ext_planning"] = min(100, round(reasoning_avg))
        raw["livebench"]["reasoning_avg"] = round(reasoning_avg, 1)
    lb_if_avg = _livebench_category_avg(lb_entry, LIVEBENCH_IF_TASKS)
    if lb_if_avg is not None:
        raw["livebench"]["if_avg"] = round(lb_if_avg, 1)
    return lb_entry


def _match_model(
    model_id: str,
    models_dev_data: list[dict[str, Any]],
    benchmark_data: list[dict[str, Any]],
    bfcl_data: list[dict[str, Any]],
    livebench_data: list[dict[str, Any]],
    catalog_entry: ModelEntry,
) -> dict[str, Any] | None:
    """Match a catalog model_id to all external data sources.

    Returns dict with enrichment fields, or None if no match found.
    """
    bare_id = _bare_model_id(model_id)
    family = catalog_entry.family
    enrichment: dict[str, Any] = {}
    raw: dict[str, Any] = {}

    dev_entry = _find_in_models_dev(bare_id, models_dev_data)
    if dev_entry:
        raw["models_dev"] = dev_entry
        enrichment.update(_extract_models_dev_fields(dev_entry))

    bench_entry = _find_in_benchmarks(bare_id, family, benchmark_data)
    if bench_entry:
        raw["benchmarks"] = bench_entry
        enrichment.update(_extract_benchmark_fields(bench_entry))

    _apply_bfcl(bare_id, family, bfcl_data, enrichment, raw)
    lb_entry = _apply_livebench(bare_id, family, livebench_data, enrichment, raw)

    instruction = _compute_instruction_score(bench_entry, lb_entry)
    if instruction is not None:
        enrichment["ext_instruction"] = instruction

    if not enrichment and not raw:
        return None

    enrichment["raw_benchmark_data"] = raw
    return enrichment
