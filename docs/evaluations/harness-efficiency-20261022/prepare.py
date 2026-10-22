"""Freeze identical tiny source-inspection and bug-fix workspaces before runs."""

import hashlib
import json
import subprocess
from pathlib import Path

BASE = Path("/srv/workspaces/agent-reviews/harness-efficiency-20261022")
DOCS = Path(__file__).resolve().parent
TASK = """Complete this ordinary Python coding fixture in the current directory. Read README.md and relevant source. Fix windows.py and paging.py to meet README.md. Write inspection.json answering the source-inspection questions in README.md. Preserve other files and work. Work only here; do not delegate, consult another model, browse, create tasks, commit, deploy, or change shared settings. Run the supplied deterministic acceptance check using the command in README.md. Finish with a concise result. This is an experiment subject, not a project worker; no extra lifecycle is needed."""
FILES = {
    "windows.py": '''"""Helpers for report time windows."""\n\ndef merge_windows(windows):\n    merged = [list(windows[0])]\n    for start, end in windows[1:]:\n        if start < merged[-1][1]:\n            merged[-1][1] = end\n        else:\n            merged.append([start, end])\n    return [tuple(pair) for pair in merged]\n''',
    "paging.py": '''"""Collect records from a cursor-based local source."""\n\ndef collect_pages(fetch_page):\n    cursor = None\n    items = []\n    while True:\n        page = fetch_page(cursor)\n        items.extend(page["items"])\n        cursor = page["next_cursor"]\n        if not cursor:\n            return items\n''',
    "catalog.py": '''"""Display labels for imported records."""\n\nDEFAULT_LABEL = "untitled"\n\ndef resolve_label(record, overrides):\n    key = record["id"]\n    if key in overrides:\n        return overrides[key]\n    if "label" in record:\n        return record["label"]\n    return DEFAULT_LABEL\n\ndef format_record(record, overrides):\n    return f'{record["id"]}: {resolve_label(record, overrides)}'\n''',
}
README = """# Local report utilities\n\nFix these two functions without changing public signatures:\n\n- `merge_windows(windows)` accepts valid `(start,end)` pairs with start <= end. Return sorted tuple pairs merging overlapping OR touching windows, including nested/duplicate/negative/zero-width intervals. Empty input returns []. Never mutate the input.\n- `collect_pages(fetch_page)` starts by calling fetch_page(None). Concatenate items in page order until next_cursor is None. Zero and empty-string cursors are valid. Raise ValueError before fetching the same non-None cursor twice. Cursors are hashable strings/integers.\n\nInspect catalog.py and create inspection.json with exactly these keys: function (the label-resolving function name), precedence (three names: override, record, default in actual order), empty_override (resolved label when an override for that id is an empty string), missing_label (result when both override and record label are absent).\n\nRun `st check cleanroom --project-root . -- python ACCEPTANCE .` for deterministic acceptance. Do not edit the acceptance program, README, catalog, configuration or frozen digest list. Only windows.py, paging.py and inspection.json are deliverables.\n"""


def prepare(name, optional, harness):
    root = BASE / "runs" / name
    root.mkdir(parents=True, exist_ok=False)
    for file, content in FILES.items():
        (root / file).write_text(content)
    (root / "README.md").write_text(README.replace("ACCEPTANCE", str(DOCS / "acceptance.py")))
    (root / "condition.json").write_text(json.dumps({"harness": harness, "optional_context": optional, "task": TASK, "context_payload": str(BASE / "private" / ("payload-on.txt" if optional else "payload-off.txt"))}, indent=2))
    pi_dir = root / ".pi"
    (pi_dir / "extensions").mkdir(parents=True)
    (pi_dir / "extensions" / "trial.js").symlink_to(DOCS / "pi-observer.js")
    # Replace only the optional AH transport, preserving all other native
    # extensions and controls. Both arms receive verified required context.
    (pi_dir / "settings.json").write_text(json.dumps({"defaultThinkingLevel": "xhigh", "extensions": ["-/home/kasadis/.pi/agent/extensions/agent-hub.ts"]}))
    frozen = {file: hashlib.sha256((root / file).read_bytes()).hexdigest() for file in ["catalog.py", "README.md", "condition.json"]}
    (root / "frozen.json").write_text(json.dumps(frozen, indent=2))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "Frozen ordinary coding subject"], check=True)
    return root


if __name__ == "__main__":
    import sys
    print(prepare(sys.argv[1], sys.argv[2] == "on", sys.argv[3]))
