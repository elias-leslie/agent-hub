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
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ARTIFACT_NAME = "Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf"
ARTIFACT_SHA256 = "58fd826723939933dc86f45b7fe04545cbc2de1c70f6fe2cdd3858c87a98c12f"
LLAMA_CPP_COMMIT = "f1e44dcc11d8802d107bd7331a3d3fd3e6f57b93"
SERVER_ALIAS = "qwen3.8-27b-neri-iq3_s"
ALLOWED_CONTEXTS = frozenset({32_768, 65_536})
ALLOWED_CACHE_TYPES = frozenset({"q4_0", "q8_0"})
ALLOWED_BATCH_SIZES = frozenset({512, 1_024, 2_048})
ALLOWED_UBATCH_SIZES = frozenset({256, 512, 1_024})
RUNTIME_RECEIPT_NAME = "agent-hub-neri-local-qwen.json"


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    if value not in {"0", "1"}:
        raise RuntimeError(f"{name} must be 0 or 1")
    return value == "1"


def _process_start_ticks(pid: int | str = "self") -> int:
    fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
    if len(fields) < 22:
        raise RuntimeError("could not read managed runtime process start identity")
    return int(fields[21])


@dataclass(frozen=True, slots=True)
class NeriQwenRuntimeConfig:
    """Validated non-secret knobs for one controlled runtime profile."""

    context_tokens: int
    mtp_enabled: bool
    spec_draft_n_max: int
    cache_type_k: str
    cache_type_v: str
    batch_size: int
    ubatch_size: int
    prompt_cache_enabled: bool
    idle_sleep_seconds: int

    @classmethod
    def from_environment(cls) -> NeriQwenRuntimeConfig:
        config = cls(
            context_tokens=int(os.environ.get("NERI_LOCAL_QWEN_CONTEXT", "32768")),
            mtp_enabled=_env_bool("NERI_LOCAL_QWEN_ENABLE_MTP", True),
            spec_draft_n_max=int(
                os.environ.get("NERI_LOCAL_QWEN_SPEC_DRAFT_N_MAX", "3")
            ),
            cache_type_k=os.environ.get("NERI_LOCAL_QWEN_CACHE_TYPE_K", "q4_0"),
            cache_type_v=os.environ.get("NERI_LOCAL_QWEN_CACHE_TYPE_V", "q4_0"),
            batch_size=int(os.environ.get("NERI_LOCAL_QWEN_BATCH_SIZE", "2048")),
            ubatch_size=int(os.environ.get("NERI_LOCAL_QWEN_UBATCH_SIZE", "512")),
            prompt_cache_enabled=_env_bool("NERI_LOCAL_QWEN_CACHE_PROMPT", True),
            idle_sleep_seconds=int(
                os.environ.get("NERI_LOCAL_QWEN_IDLE_SLEEP_SECONDS", "300")
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.context_tokens not in ALLOWED_CONTEXTS:
            raise RuntimeError(f"context must be one of {sorted(ALLOWED_CONTEXTS)}")
        if self.cache_type_k not in ALLOWED_CACHE_TYPES:
            raise RuntimeError(f"K cache type must be one of {sorted(ALLOWED_CACHE_TYPES)}")
        if self.cache_type_v not in ALLOWED_CACHE_TYPES:
            raise RuntimeError(f"V cache type must be one of {sorted(ALLOWED_CACHE_TYPES)}")
        if self.batch_size not in ALLOWED_BATCH_SIZES:
            raise RuntimeError(f"batch size must be one of {sorted(ALLOWED_BATCH_SIZES)}")
        if self.ubatch_size not in ALLOWED_UBATCH_SIZES:
            raise RuntimeError(f"ubatch size must be one of {sorted(ALLOWED_UBATCH_SIZES)}")
        if self.ubatch_size > self.batch_size:
            raise RuntimeError("ubatch size cannot exceed batch size")
        if not 1 <= self.spec_draft_n_max <= 8:
            raise RuntimeError("MTP draft length must be between 1 and 8")
        if not 60 <= self.idle_sleep_seconds <= 3_600:
            raise RuntimeError("idle sleep must be between 60 and 3600 seconds")

    def public_metadata(self) -> dict[str, int | str | bool]:
        return asdict(self)


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


def _build_command(
    binary: Path,
    model: Path,
    config: NeriQwenRuntimeConfig,
) -> list[str]:
    command = [
        str(binary),
        "-m",
        str(model),
        "--alias",
        SERVER_ALIAS,
        "-ngl",
        "99",
        "-c",
        str(config.context_tokens),
        "--cache-type-k",
        config.cache_type_k,
        "--cache-type-v",
        config.cache_type_v,
        "--batch-size",
        str(config.batch_size),
        "--ubatch-size",
        str(config.ubatch_size),
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
        "--sleep-idle-seconds",
        str(config.idle_sleep_seconds),
    ]
    command.append("--cache-prompt" if config.prompt_cache_enabled else "--no-cache-prompt")
    if config.mtp_enabled:
        command.extend(
            [
                "--spec-type",
                "draft-mtp",
                "--spec-draft-n-max",
                str(config.spec_draft_n_max),
            ]
        )
    return command


def _write_runtime_receipt(
    runtime_dir: Path,
    config: NeriQwenRuntimeConfig,
    *,
    binary: Path,
    model: Path,
) -> None:
    """Publish the exact managed launch profile for benchmark provenance."""
    receipt_path = runtime_dir / RUNTIME_RECEIPT_NAME
    temporary_path = runtime_dir / f".{RUNTIME_RECEIPT_NAME}.{os.getpid()}"
    payload = {
        "pid": os.getpid(),
        "process_start_ticks": _process_start_ticks(),
        "artifact_sha256": ARTIFACT_SHA256,
        "engine_revision": LLAMA_CPP_COMMIT,
        "server_model_id": SERVER_ALIAS,
        "binary_path": str(binary),
        "model_path": str(model),
        **config.public_metadata(),
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary_path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, receipt_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    binary = _server_binary()
    model = _model_path()
    config = NeriQwenRuntimeConfig.from_environment()
    _verify_runtime(binary, model)
    if args.check_only:
        print(
            json.dumps(
                {
                    "status": "ready",
                    "artifact_sha256": ARTIFACT_SHA256,
                    "llama_cpp_commit": LLAMA_CPP_COMMIT,
                    "server_alias": SERVER_ALIAS,
                    **config.public_metadata(),
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
    _write_runtime_receipt(runtime_dir, config, binary=binary, model=model)
    command = _build_command(binary, model, config)
    os.execv(command[0], command)


if __name__ == "__main__":
    main()
