"""Deterministic acceptance for the frozen, synthetic coding subject."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


def load(root, name):
    spec = importlib.util.spec_from_file_location(name, root / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evaluate(root):
    checks = {}

    def check(name, fn):
        try:
            assert fn()
            checks[name] = True
        except Exception:
            checks[name] = False

    windows = load(root, "windows")
    paging = load(root, "paging")
    cases = [([], []), ([(2, 3)], [(2, 3)]),
             ([(5, 8), (1, 3), (3, 6)], [(1, 8)]),
             ([(1, 10), (2, 3), (12, 15)], [(1, 10), (12, 15)]),
             ([(-4, -1), (-2, 0), (3, 4)], [(-4, 0), (3, 4)]),
             ([(1, 1), (1, 2), (1, 2)], [(1, 2)])]
    for i, (value, expected) in enumerate(cases):
        check(f"windows_{i}", lambda v=value, e=expected: windows.merge_windows(v) == e)
    source = [(5, 8), (1, 3), (3, 6)]
    before = source.copy()
    check("windows_no_mutation", lambda: windows.merge_windows(source) == [(1, 8)] and source == before)

    def pages(sequence, expected_items, expected_calls):
        calls = []

        def fetch(cursor):
            calls.append(cursor)
            assert len(calls) <= 8
            return sequence[len(calls) - 1]

        return paging.collect_pages(fetch) == expected_items and calls == expected_calls

    check("paging_zero", lambda: pages([{"items": ["a"], "next_cursor": 0}, {"items": ["b"], "next_cursor": None}], ["a", "b"], [None, 0]))
    check("paging_empty_string", lambda: pages([{"items": [], "next_cursor": ""}, {"items": ["b"], "next_cursor": None}], ["b"], [None, ""]))
    check("paging_normal", lambda: pages([{"items": [1], "next_cursor": "p2"}, {"items": [2, 3], "next_cursor": None}], [1, 2, 3], [None, "p2"]))
    check("paging_empty", lambda: pages([{"items": [], "next_cursor": None}], [], [None]))

    def cycle():
        calls = []

        def fetch(cursor):
            calls.append(cursor)
            if len(calls) > 5:
                raise RuntimeError("unbounded loop")
            return {"items": [], "next_cursor": "same"}

        try:
            paging.collect_pages(fetch)
        except ValueError:
            return len(calls) == 2
        return False

    check("paging_cycle", cycle)
    check("inspection", lambda: json.loads((root / "inspection.json").read_text()) == {
        "function": "resolve_label", "precedence": ["override", "record", "default"],
        "empty_override": "", "missing_label": "untitled"})
    frozen = json.loads((root / "frozen.json").read_text())
    for name, digest in frozen.items():
        check(f"preserved_{name}", lambda n=name, d=digest: hashlib.sha256((root / n).read_bytes()).hexdigest() == d)
    return {"accepted": all(checks.values()), "passed": sum(checks.values()),
            "total": len(checks), "checks": checks}


if __name__ == "__main__":
    result = evaluate(Path(sys.argv[1]))
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["accepted"] else 1)
