#!/usr/bin/env python3
"""Launch the pinned Neri Qwen llama.cpp runtime under an exclusive GPU lease."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ARTIFACT_NAME = "Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf"
ARTIFACT_SHA256 = "58fd826723939933dc86f45b7fe04545cbc2de1c70f6fe2cdd3858c87a98c12f"
LLAMA_CPP_COMMIT = "f1e44dcc11d8802d107bd7331a3d3fd3e6f57b93"
SERVER_ALIAS = "qwen3.8-27b-neri-iq3_s"
ALLOWED_CONTEXTS = frozenset({32_768, 65_536})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_path() -> Path:
    configured = os.environ.get("NERI_LOCAL_QWEN_MODEL_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".cache" / "agent-hub" / "models" / ARTIFACT_NAME).resolve()


def _server_binary() -> Path:
    configured = os.environ.get("NERI_LLAMA_SERVER_BIN")
    candidate = configured or shutil.which("llama-server") or str(Path.home() / ".local/bin/llama-server")
    return Path(candidate).expanduser().resolve()


def _verify_runtime(binary: Path, model: Path) -> None:
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(f"llama-server is not executable at {binary}")
    if not model.is_file():
        raise RuntimeError(f"pinned model artifact is missing at {model}")
    version = subprocess.run(
        [str(binary), "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    version_text = f"{version.stdout}\n{version.stderr}".lower()
    if LLAMA_CPP_COMMIT[:7] not in version_text:
        raise RuntimeError(
            f"llama-server revision mismatch: expected commit {LLAMA_CPP_COMMIT}"
        )
    devices = subprocess.run(
        [str(binary), "--list-devices"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if "CUDA0:" not in f"{devices.stdout}\n{devices.stderr}":
        raise RuntimeError("llama-server does not expose the required CUDA0 backend")
    actual = _sha256(model)
    if actual != ARTIFACT_SHA256:
        raise RuntimeError(f"model artifact SHA-256 mismatch: expected {ARTIFACT_SHA256}, got {actual}")


def _unload_ollama_models() -> list[str]:
    """Release Ollama GPU allocations before llama.cpp acquires the device."""
    try:
        with urlopen("http://127.0.0.1:11434/api/ps", timeout=2) as response:
            payload = json.load(response)
    except (OSError, URLError, ValueError):
        return []
    names = [
        str(row.get("name"))
        for row in payload.get("models", [])
        if isinstance(row, dict) and row.get("name")
    ]
    unloaded: list[str] = []
    for name in names:
        body = json.dumps({"model": name, "prompt": "", "keep_alive": 0}).encode()
        request = Request(
            "http://127.0.0.1:11434/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                response.read()
            unloaded.append(name)
        except (OSError, URLError):
            raise RuntimeError(f"could not release Ollama model {name}") from None
    return unloaded


def _build_command(binary: Path, model: Path, context_tokens: int, enable_mtp: bool) -> list[str]:
    command = [
        str(binary),
        "-m",
        str(model),
        "--alias",
        SERVER_ALIAS,
        "-ngl",
        "99",
        "-c",
        str(context_tokens),
        "--cache-type-k",
        "q4_0",
        "--cache-type-v",
        "q4_0",
        "-fa",
        "on",
        "--jinja",
        "--reasoning-preserve",
        "--parallel",
        "1",
        "--fit",
        "off",
        "--temp",
        "1.0",
        "--top-p",
        "0.95",
        "--top-k",
        "20",
        "--min-p",
        "0.0",
        "--host",
        "127.0.0.1",
        "--port",
        "8100",
        "--cors-origins",
        "localhost",
        "--no-webui",
    ]
    if enable_mtp:
        command.extend(["--spec-type", "draft-mtp", "--spec-draft-n-max", "2"])
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    binary = _server_binary()
    model = _model_path()
    context_tokens = int(os.environ.get("NERI_LOCAL_QWEN_CONTEXT", "32768"))
    if context_tokens not in ALLOWED_CONTEXTS:
        raise RuntimeError(f"context must be one of {sorted(ALLOWED_CONTEXTS)}")
    enable_mtp = os.environ.get("NERI_LOCAL_QWEN_ENABLE_MTP", "0") == "1"
    _verify_runtime(binary, model)
    if args.check_only:
        print(
            json.dumps(
                {
                    "status": "ready",
                    "artifact_sha256": ARTIFACT_SHA256,
                    "llama_cpp_commit": LLAMA_CPP_COMMIT,
                    "server_alias": SERVER_ALIAS,
                    "context_tokens": context_tokens,
                    "mtp": enable_mtp,
                }
            )
        )
        return

    runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = runtime_dir / "agent-hub-gpu-inference.lock"
    lock_handle = lock_path.open("a+")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError("another managed local inference workload holds the GPU lease") from None
    os.set_inheritable(lock_handle.fileno(), True)
    unloaded = _unload_ollama_models()
    if unloaded:
        print(f"Released Ollama GPU models: {', '.join(unloaded)}", file=sys.stderr)
    command = _build_command(binary, model, context_tokens, enable_mtp)
    os.execv(command[0], command)


if __name__ == "__main__":
    main()
