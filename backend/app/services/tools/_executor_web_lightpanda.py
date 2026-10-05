"""Pinned, opt-in Lightpanda DOM retrieval. It does not provide visual rendering."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from app.utils.safe_subprocess import create_process

PINNED_VERSION = "1.1.0-nightly.10071+3be033135"
PINNED_SHA256 = "e24d135bb5c4c0905cea9ee9a1cd87eff407755af24bd99b659fa64ec907f18d"
_VERIFIED: dict[tuple[object, ...], dict[str, Any]] = {}


class _ProcessTimeout(TimeoutError):
    def __init__(self, stdout: bytes, stderr: bytes) -> None:
        super().__init__("process deadline exceeded")
        self.stdout = stdout
        self.stderr = stderr


def _configuration() -> tuple[Path, str, str]:
    override = os.environ.get("AGENT_HUB_WEB_LIGHTPANDA_BINARY")
    version = os.environ.get("AGENT_HUB_WEB_LIGHTPANDA_VERSION")
    digest = os.environ.get("AGENT_HUB_WEB_LIGHTPANDA_SHA256")
    if override and (not version or not digest):
        raise ValueError("Lightpanda binary override requires paired VERSION and SHA256 pins")
    if not override and (version or digest):
        raise ValueError("Lightpanda pin overrides require an explicit BINARY path")
    data = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    path = Path(override) if override else data / "agent-hub/web/lightpanda" / PINNED_SHA256 / "lightpanda"
    if not path.is_absolute():
        raise ValueError("Lightpanda binary must be an absolute path")
    return path, version or PINNED_VERSION, digest or PINNED_SHA256


def _verify_binary(path: Path, digest: str) -> None:
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError(f"Lightpanda executable is unavailable: {path}")
    with path.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if actual != digest:
        raise ValueError("Lightpanda SHA256 does not match configured pin")


def _binary_signature(path: Path, version: str, digest: str) -> tuple[object, ...]:
    stat = path.stat()
    return (str(path), version, digest, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


async def _run(args: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    env = {**os.environ, "LIGHTPANDA_DISABLE_TELEMETRY": "1"}
    process = await create_process(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
    )
    communication = asyncio.create_task(process.communicate())
    try:
        stdout, stderr = await asyncio.wait_for(asyncio.shield(communication), timeout=timeout)
    except TimeoutError:
        _kill_process_group(process.pid)
        stdout, stderr = await communication
        raise _ProcessTimeout(stdout, stderr) from None
    except asyncio.CancelledError:
        _kill_process_group(process.pid)
        await communication
        raise
    return process.returncode or 0, stdout, stderr


def _kill_process_group(pid: int) -> None:
    # The shared launcher starts a fresh session; also kill descendants holding pipes.
    with suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGKILL)


async def doctor_lightpanda(timeout: float = 20.0, *, force: bool = True) -> dict[str, Any]:
    started = time.monotonic()
    payload: dict[str, Any] = {"backend": "lightpanda", "telemetry_disabled": True}
    try:
        path, version, digest = _configuration()
        payload.update(binary_path=str(path), pinned_version=version, pinned_sha256=digest)
        signature = _binary_signature(path, version, digest)
        if not force and signature in _VERIFIED:
            return {**_VERIFIED[signature], "verification_cached": True,
                    "verification_ms": round((time.monotonic() - started) * 1000, 3)}
        await asyncio.to_thread(_verify_binary, path, digest)
        code, stdout, stderr = await _run([str(path), "version"], timeout)
        actual = stdout.decode(errors="replace").strip()
        payload["actual_version"] = actual
        if code or actual.removeprefix("lightpanda ").removeprefix("v") != version:
            raise ValueError(f"Lightpanda version pin mismatch: {actual}; {stderr.decode(errors='replace')}")
        payload["usable"] = True
        if _binary_signature(path, version, digest) != signature:
            raise ValueError("Lightpanda binary changed during verification")
        _VERIFIED[signature] = {**payload, "verification_cached": False}
    except (OSError, ValueError, TimeoutError) as exc:
        payload.update(usable=False, error="Lightpanda verification failed", detail=str(exc) or "verification timeout")
    payload["verification_ms"] = round((time.monotonic() - started) * 1000, 3)
    return payload


async def fetch_lightpanda(url: str, *, selector: str | None, wait_script: str | None, timeout: float) -> dict[str, Any]:
    verification = await doctor_lightpanda(timeout, force=False)
    if not verification["usable"]:
        return verification
    args = [verification["binary_path"], "fetch", url, "--json", "--dump", "markdown",
            "--fail-on-http-error", "--wait-until", "domcontentloaded",
            "--terminate-ms", str(max(1, int(timeout * 1000))),
            "--http-timeout", str(max(1, int(timeout * 1000)))]
    if selector:
        args.extend(["--dump-selector", selector])
    if wait_script:
        args.extend(["--wait-script", wait_script])
    started = time.monotonic()
    result: dict[str, Any] = {"lightpanda": verification}
    stdout, stderr = b"", b""
    try:
        code, stdout, stderr = await _run(args, timeout)
        receipt = json.loads(stdout)
        if (not isinstance(receipt, dict) or not isinstance(receipt.get("content"), str)
            or not isinstance(receipt.get("http_status"), int) or isinstance(receipt.get("http_status"), bool)
            or not 100 <= receipt["http_status"] <= 599
            or not isinstance(receipt.get("url"), str) or not receipt["url"].startswith(("http://", "https://"))
            or "error" not in receipt or (receipt["error"] is not None and not isinstance(receipt["error"], str))):
            raise ValueError("Lightpanda returned an invalid fetch receipt")
        result.update(receipt)
        result["process_exit_code"] = code
        if stderr:
            result["stderr"] = stderr.decode(errors="replace")
        if code or receipt.get("error") or receipt["http_status"] >= 400 or not receipt["content"].strip():
            result["error"] = receipt.get("error") or ("Lightpanda HTTP request failed" if receipt["http_status"] >= 400 else "Lightpanda empty extraction" if not receipt["content"].strip() else "Lightpanda process failed")
    except _ProcessTimeout as exc:
        result.update(error="Lightpanda fetch timed out", detail=f"process deadline {timeout:g}s exceeded; process killed and reaped",
                      raw_receipt=exc.stdout.decode(errors="replace"), stderr=exc.stderr.decode(errors="replace"))
    except (OSError, ValueError) as exc:
        result.update(error="Lightpanda fetch failed", detail=str(exc),
                      raw_receipt=stdout.decode(errors="replace"), stderr=stderr.decode(errors="replace"))
    result["fetch_ms"] = round((time.monotonic() - started) * 1000, 3)
    return result
