#!/usr/bin/env python3
"""Audit Agent Hub's pi-mono port against the recorded catalog."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "tasks" / "agent-framework-convergence" / "pi-mono-catalog.md"
LLM = ROOT / "app" / "llm"
DEFAULT_REPO = Path.home() / "references" / "pi-mono"
REMOTE = "https://github.com/badlogic/pi-mono.git"


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    return proc.returncode, (proc.stdout or proc.stderr).strip()


def catalog_sha(text: str) -> str | None:
    match = re.search(r"Tip SHA:\*\* `([0-9a-f]{7,40})`", text)
    return match.group(1) if match else None


def latest_sha(repo: Path) -> tuple[str | None, str]:
    if (repo / ".git").exists():
        _run(["git", "fetch", "--quiet", "origin"], cwd=repo)
        code, out = _run(["git", "rev-parse", "origin/main"], cwd=repo)
        if code == 0:
            return out, f"local:{repo}"
    code, out = _run(["git", "ls-remote", REMOTE, "HEAD"])
    if code != 0:
        return None, out
    return out.split()[0], "remote:HEAD"


def catalog_exports(text: str) -> set[str]:
    names = set(re.findall(r"\bexport\s+(?:interface|type|class|function|const)\s+([A-Za-z_][A-Za-z0-9_]*)", text))
    names.update(re.findall(r"`([A-Z][A-Za-z0-9_]+)`", text))
    return names


def python_exports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    names.add(target.id)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and not node.target.id.startswith("_")
        ):
            names.add(node.target.id)
    return names


def current_surface() -> set[str]:
    files = [
        LLM / "types.py",
        LLM / "api_registry.py",
        LLM / "event_stream.py",
        LLM / "stream.py",
        LLM / "transform_messages.py",
        LLM / "simple_options.py",
    ]
    names: set[str] = set()
    for path in files:
        names.update(python_exports(path))
    names.update(path.stem for path in (LLM / "providers").glob("*.py") if path.name != "__init__.py")
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO, help="local pi-mono checkout")
    args = parser.parse_args()

    catalog = CATALOG.read_text()
    recorded = catalog_sha(catalog)
    latest, source = latest_sha(args.repo)
    catalog_names = catalog_exports(catalog)
    current_names = current_surface()

    print(f"catalog_sha: {recorded or 'unknown'}")
    print(f"latest_sha: {latest or 'unknown'} ({source})")
    if recorded and latest and not latest.startswith(recorded):
        print("catalog_status: STALE")
        print(f"upstream_diff_hint: git -C {args.repo} diff {recorded} {latest} -- packages/ai/src")
    else:
        print("catalog_status: current-or-unverified")

    missing = sorted(name for name in catalog_names - current_names if name[:1].isupper())
    extra = sorted(current_names - catalog_names)

    print("\nnew_or_unmapped_catalog_primitives:")
    for name in missing[:80]:
        print(f"- {name}")
    if not missing:
        print("- none")

    print("\nagent_hub_names_without_catalog_match:")
    for name in extra[:80]:
        print(f"- {name}")
    if not extra:
        print("- none")

    return 0


if __name__ == "__main__":
    sys.exit(main())
