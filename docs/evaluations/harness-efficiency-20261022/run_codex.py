"""One headless native Codex subject, preserving native config and rules."""

import json
import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path


def main(root):
    condition = json.loads((root / "condition.json").read_text())
    payload = Path(condition["context_payload"]).read_text()
    # Match the official additive launcher behavior: preserve configured user
    # developer instructions. The native system, rules, hooks and tools stay on.
    config_file = Path.home() / ".codex/config.toml"
    config = tomllib.loads(config_file.read_text()) if config_file.exists() else {}
    existing = config.get("developer_instructions", "")
    instructions = "\n\n".join(v for v in [existing, payload] if v)
    native = os.environ.get("CODEX_REAL", str(Path.home() / ".local/bin/codex-real"))
    private = Path(condition["context_payload"]).parent / root.name
    private.mkdir(exist_ok=True)
    started = time.time()
    (root / "attempt.json").write_text(json.dumps({"started": started, "harness": "codex", "arm": "on" if condition["optional_context"] else "off"}))
    command = [native, "exec", "--json", "--model", "gpt-6.1-sol", "--sandbox", "danger-full-access", "-c", "approval_policy=\"never\"", "-c", "model_reasoning_effort=\"xhigh\"", "-c", "service_tier=\"default\"", "-c", "developer_instructions=" + json.dumps(instructions), "-C", str(root), "-"]
    with (private / "stdout.jsonl").open("w") as out, (private / "stderr.log").open("w") as err:
        result = subprocess.run(command, input=condition["task"], text=True, stdout=out, stderr=err)
    receipt = {"started": started, "ended": time.time(), "whole_seconds": time.time() - started, "exit_code": result.returncode}
    events = []
    for line in (private / "stdout.jsonl").read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if value["type"] in ["thread.started", "turn.completed", "turn.failed", "error"]:
            events.append(value)
    receipt["events"] = events
    (root / "result.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
