#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"missing log file: {path}")
    entries: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid json on line {line_number}: {exc}") from exc
        required = {"timestamp", "route", "status", "observation_type"}
        missing = sorted(required - data.keys())
        if missing:
            raise ValueError(f"line {line_number} missing fields: {', '.join(missing)}")
        entries.append(data)
    return entries


def latest_by_route(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for entry in entries:
        latest[entry["route"]] = entry
    return latest


def compare(entries: list[dict[str, Any]]) -> tuple[int, list[str]]:
    by_route: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        by_route[entry["route"]].append(entry)

    findings: list[str] = []
    exit_code = 0
    for route in sorted(by_route):
        route_entries = by_route[route]
        baseline = route_entries[0]
        current = route_entries[-1]
        if baseline["status"] != current["status"]:
            findings.append(
                f"REGRESSION route={route} status {baseline['status']} -> {current['status']} at {current['timestamp']}"
            )
            exit_code = 1
        if baseline["observation_type"] != current["observation_type"]:
            findings.append(
                f"PATTERN route={route} observation_type {baseline['observation_type']} -> {current['observation_type']} at {current['timestamp']}"
            )
            exit_code = 1
        if current.get("critical_count", 0) > 0 or current.get("warning_count", 0) > 0:
            findings.append(
                f"ALERT route={route} critical={current.get('critical_count', 0)} warning={current.get('warning_count', 0)} at {current['timestamp']}"
            )
            exit_code = 1

    if not findings:
        latest = latest_by_route(entries)
        findings.append(
            f"OK healthy baseline holds for {len(latest)} routes; latest timestamps: "
            + ", ".join(f"{route}={data['timestamp']}" for route, data in sorted(latest.items()))
        )
    return exit_code, findings


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("logs/health-observations.jsonl")
    entries = load_entries(path)
    code, findings = compare(entries)
    for line in findings:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
