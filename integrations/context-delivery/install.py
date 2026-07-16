#!/usr/bin/env python3
"""Install or verify source-linked Agent Hub context adapters."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import stat
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SURFACES = ("claude_code", "codex", "gemini", "pi")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install source-linked canonical Agent Hub context adapters."
    )
    parser.add_argument("--surface", action="append", choices=SURFACES)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--check", action="store_true", help="Report drift without changing files")
    return parser


def _load_manifest(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "integrations/context-delivery/manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "agent-hub.context-adapters.v1":
        raise RuntimeError(f"unsupported adapter manifest at {path}")
    return value


def _selected(args: argparse.Namespace) -> set[str]:
    return set(args.surface or SURFACES)


def _source(repo_root: Path, raw: str) -> Path:
    return (repo_root / raw).resolve()


def _target(home: Path, raw: str) -> Path:
    # Keep the lexical install location. Path.resolve() would follow an already
    # installed symlink and make drift checks inspect the source as the target.
    return Path(os.path.abspath(home / raw))


def _same_link(target: Path, source: Path) -> bool:
    return target.is_symlink() and target.resolve(strict=False) == source


def _backup_file(home: Path, target: Path) -> Path:
    relative = target.relative_to(home)
    root = home / ".local/state/agent-hub/adapter-backups"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    digest = hashlib.sha256(str(relative).encode("utf-8")).hexdigest()[:12]
    destination = root / f"{stamp}-{digest}-{target.name}"
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copy2(target, destination)
    os.chmod(destination, stat.S_IRUSR)
    return destination


def _install_link(home: Path, source: Path, target: Path) -> dict[str, str]:
    if not source.exists():
        raise RuntimeError(f"canonical adapter source is missing: {source}")
    if _same_link(target, source):
        return {"target": str(target), "state": "ok", "source": str(source)}

    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if target.exists() and not target.is_symlink():
        backup = _backup_file(home, target)
    temporary = target.with_name(f".{target.name}.agent-hub-{uuid.uuid4().hex}")
    os.symlink(source, temporary)
    os.replace(temporary, target)
    result = {"target": str(target), "state": "linked", "source": str(source)}
    if backup:
        result["backup"] = str(backup)
    return result


def _check_link(source: Path, target: Path) -> dict[str, str]:
    if not source.exists():
        return {"target": str(target), "state": "missing-source", "source": str(source)}
    if _same_link(target, source):
        return {"target": str(target), "state": "ok", "source": str(source)}
    return {"target": str(target), "state": "drift", "source": str(source)}


def _retire(home: Path, target: Path) -> dict[str, str]:
    if not target.exists() and not target.is_symlink():
        return {"target": str(target), "state": "ok"}
    backup = _backup_file(home, target)
    target.unlink()
    return {"target": str(target), "state": "retired", "backup": str(backup)}


def _check_retired(target: Path) -> dict[str, str]:
    state = "legacy" if target.exists() or target.is_symlink() else "ok"
    return {"target": str(target), "state": state}


def _remove_legacy_hooks(groups: list[Any], fragments: list[str]) -> list[Any]:
    if not fragments:
        return groups
    cleaned: list[Any] = []
    for group in groups:
        if not isinstance(group, dict):
            cleaned.append(group)
            continue
        direct = group.get("command")
        if isinstance(direct, str) and any(fragment in direct for fragment in fragments):
            continue
        if isinstance(group.get("hooks"), list):
            hooks = [
                hook
                for hook in group["hooks"]
                if not (
                    isinstance(hook, dict)
                    and isinstance(hook.get("command"), str)
                    and any(fragment in hook["command"] for fragment in fragments)
                )
            ]
            if not hooks:
                continue
            group = {**group, "hooks": hooks}
        cleaned.append(group)
    return cleaned


def _expected_hook_group(entry: dict[str, Any], home: Path) -> dict[str, Any]:
    native_hook = {
        "type": "command",
        "command": entry["command"].format(home=home),
        "timeout": entry["timeout"],
    }
    group: dict[str, Any] = {"hooks": [native_hook]}
    if "matcher" in entry:
        group["matcher"] = entry["matcher"]
    if "sequential" in entry:
        group["sequential"] = entry["sequential"]
    return group


def _remove_exact_command(groups: list[Any], command: str) -> list[Any]:
    cleaned: list[Any] = []
    for group in groups:
        if not isinstance(group, dict):
            cleaned.append(group)
            continue
        if group.get("command") == command:
            continue
        hooks = group.get("hooks")
        if not isinstance(hooks, list):
            cleaned.append(group)
            continue
        remaining = [
            hook
            for hook in hooks
            if not (isinstance(hook, dict) and hook.get("command") == command)
        ]
        if remaining:
            cleaned.append({**group, "hooks": remaining})
    return cleaned


def _contains_exact_command(groups: list[Any], command: str) -> bool:
    for group in groups:
        if not isinstance(group, dict):
            continue
        if group.get("command") == command:
            return True
        hooks = group.get("hooks")
        if isinstance(hooks, list) and any(
            isinstance(hook, dict) and hook.get("command") == command for hook in hooks
        ):
            return True
    return False


def _canonical_hook_is_exact(
    hooks: dict[str, Any], entry: dict[str, Any], home: Path
) -> bool:
    expected = _expected_hook_group(entry, home)
    command = expected["hooks"][0]["command"]
    groups = hooks.get(entry["event"])
    if not isinstance(groups, list):
        return False
    matches: list[Any] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        if group.get("command") == command:
            matches.append(group)
        native_hooks = group.get("hooks")
        if not isinstance(native_hooks, list):
            continue
        for hook in native_hooks:
            if isinstance(hook, dict) and hook.get("command") == command:
                matches.append(group)
    return matches == [expected]


def _merge_hook(path: Path, entry: dict[str, Any], home: Path) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"settings root must be a JSON object: {path}")
    else:
        value = {}
    original = copy.deepcopy(value)
    hooks = value.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise RuntimeError(f"settings hooks must be a JSON object: {path}")
    fragments = entry.get("remove_commands_containing", [])
    if fragments:
        for existing_event, existing_groups in list(hooks.items()):
            if isinstance(existing_groups, list):
                hooks[existing_event] = _remove_legacy_hooks(existing_groups, fragments)
    event = entry["event"]
    groups = hooks.setdefault(event, [])
    if not isinstance(groups, list):
        raise RuntimeError(f"settings hooks.{event} must be a JSON array: {path}")

    groups = _remove_legacy_hooks(groups, fragments)
    hooks[event] = groups
    expected = _expected_hook_group(entry, home)
    command = expected["hooks"][0]["command"]
    if entry.get("remove_same_command_from_other_events"):
        for existing_event, existing_groups in list(hooks.items()):
            if existing_event != event and isinstance(existing_groups, list):
                hooks[existing_event] = _remove_exact_command(existing_groups, command)
    if not _canonical_hook_is_exact(hooks, entry, home):
        hooks[event] = _remove_exact_command(hooks[event], command)
        hooks[event].append(expected)

    if value == original:
        return {"target": str(path), "state": "ok", "event": event, "command": command}
    if path.is_symlink():
        raise RuntimeError(
            f"source-linked settings are missing their canonical hook: {path}; "
            "update the source-controlled settings instead of mutating them at install time"
        )

    backup = _backup_file(home, path) if path.exists() else None
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = {
        "target": str(path),
        "state": "configured",
        "event": event,
        "command": command,
    }
    if backup:
        result["backup"] = str(backup)
    return result


def _check_hook(path: Path, entry: dict[str, Any], home: Path) -> dict[str, str]:
    if not path.exists():
        return {"target": str(path), "state": "missing", "event": entry["event"]}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise AttributeError("settings root is not an object")
    except (AttributeError, json.JSONDecodeError):
        return {"target": str(path), "state": "invalid", "event": entry["event"]}
    fragments = entry.get("remove_commands_containing", [])
    serialized = json.dumps(value.get("hooks", {}))
    if any(fragment in serialized for fragment in fragments):
        return {"target": str(path), "state": "legacy", "event": entry["event"]}
    hooks = value.get("hooks", {})
    command = entry["command"].format(home=home)
    if (
        entry.get("remove_same_command_from_other_events")
        and isinstance(hooks, dict)
        and any(
            event != entry["event"]
            and isinstance(groups, list)
            and _contains_exact_command(groups, command)
            for event, groups in hooks.items()
        )
    ):
        return {"target": str(path), "state": "legacy", "event": entry["event"]}
    if isinstance(hooks, dict) and _canonical_hook_is_exact(hooks, entry, home):
        return {"target": str(path), "state": "ok", "event": entry["event"]}
    return {"target": str(path), "state": "drift", "event": entry["event"]}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = (args.repo_root or Path(__file__).resolve().parents[2]).resolve()
    home = args.home.expanduser().resolve()
    manifest = _load_manifest(repo_root)
    selected = _selected(args)
    results: list[dict[str, str]] = []

    for entry in manifest["links"]:
        if entry["surface"] not in selected and entry["surface"] != "shared":
            continue
        source = _source(repo_root, entry["source"])
        target = _target(home, entry["target"])
        results.append(
            _check_link(source, target)
            if args.check
            else _install_link(home, source, target)
        )

    for entry in manifest.get("retired", []):
        if entry["surface"] not in selected:
            continue
        target = _target(home, entry["target"])
        results.append(_check_retired(target) if args.check else _retire(home, target))

    for entry in manifest["hooks"]:
        if entry["surface"] not in selected:
            continue
        path = _target(home, entry["path"])
        results.append(
            _check_hook(path, entry, home)
            if args.check
            else _merge_hook(path, entry, home)
        )

    failed = any(
        result["state"] not in {"ok", "linked", "configured", "retired"}
        for result in results
    )
    print(
        json.dumps(
            {
                "schema_version": manifest["schema_version"],
                "mode": "check" if args.check else "install",
                "surfaces": sorted(selected),
                "passed": not failed,
                "results": results,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
