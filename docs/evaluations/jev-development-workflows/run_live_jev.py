"""Run frozen, finite Jev packets once each without the Neri pilot ledger."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "backend"))

# Import the schemas first; app.api package initialization otherwise cycles through this service.
from app.api.typesafe_jev_schemas import SystemOneRequest  # noqa: E402
from app.services.memory.budget import count_tokens  # noqa: E402
from app.services.typesafe_jev import (  # noqa: E402
    JEV_INPUT_USD_PER_MILLION,
    JEV_MAX_INPUT_TOKENS,
    JEV_MODEL_ID,
    call_typesafe_jev,
    resolve_typesafe_api_key,
)

MANIFEST = HERE / "live-packets-v1.json"
RECEIPTS = HERE / "live-receipts-v1"
MODEL_WINDOW_STATE_QUESTION = 32_000  # Verified TypeSafe Jev 1.13 model contract.
HTTP_TIMEOUT_SECONDS = 30.0  # Existing Agent Hub external-HTTP precedent; default Jev transport is unbounded.


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def source_text(source_id: str) -> str | None:
    if source_id.startswith("native collaboration spawn schema"):
        return None  # Session-provided schema is retained verbatim in the packet state.
    if source_id.startswith("27f80dc5b1e83f72a6c183e00a0d337f89c1f6f2:"):
        return subprocess.run(["git", "show", source_id], cwd=ROOT, check=True,
                              capture_output=True, text=True).stdout
    return Path(source_id).read_text()


def validate(packet: dict) -> tuple[SystemOneRequest, int]:
    for source in packet["source_coverage"]:
        content = source_text(source["source_id"])
        if content is not None and sha(content) != source["sha256"]:
            raise ValueError(f"source hash changed: {source['source_id']}")
    request = SystemOneRequest.model_validate(packet["request"])
    if request.model != JEV_MODEL_ID:
        raise ValueError("model changed from verified pinned Jev version")
    state = json.dumps(request.state, sort_keys=True)
    questions = [json.dumps(q.model_dump(mode="json"), sort_keys=True) for q in request.questions.values()]
    whole = count_tokens(state + " ".join(questions))
    longest = count_tokens(state + max(questions, key=len))
    if whole > JEV_MAX_INPUT_TOKENS or longest > MODEL_WINDOW_STATE_QUESTION:
        raise ValueError("packet exceeds verified Jev context contract")
    return request, whole


def write_exclusive(path: Path, receipt: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
        json.dump(receipt, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def replace_receipt(path: Path, receipt: dict) -> None:
    temporary = path.with_suffix(".tmp")
    write_exclusive(temporary, receipt)
    os.replace(temporary, path)


async def run_one(packet: dict, manifest_hash: str, api_key: str) -> dict:
    request, estimated_tokens = validate(packet)
    request_hash = canonical_hash(packet["request"])
    path = RECEIPTS / f"{packet['id']}.json"
    if path.exists():
        existing = json.loads(path.read_text())
        if existing.get("request_sha256") != request_hash or existing.get("manifest_sha256") != manifest_hash:
            raise ValueError(f"existing receipt mismatch; use a new manifest version: {packet['id']}")
        return {"id": packet["id"], "status": existing["status"], "reused_receipt": True}
    receipt = {"id": packet["id"], "use_case": packet["use_case"], "kind": packet["kind"],
               "status": "attempted", "manifest_sha256": manifest_hash, "request_sha256": request_hash,
               "model_requested": request.model, "estimated_input_tokens": estimated_tokens,
               "max_provider_cost_usd": str(Decimal(JEV_MAX_INPUT_TOKENS) * JEV_INPUT_USD_PER_MILLION / Decimal(1_000_000)),
               "started_at_utc": datetime.now(UTC).isoformat(), "source_coverage": packet["source_coverage"],
               "request": packet["request"]}
    write_exclusive(path, receipt)
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, trust_env=False, follow_redirects=False) as client:
            response, provider_id = await call_typesafe_jev(request, api_key=api_key, http_client=client)
        cost = Decimal(response.usage.input_tokens) * JEV_INPUT_USD_PER_MILLION / Decimal(1_000_000)
        receipt.update(status="succeeded", response=response.model_dump(mode="json"),
                       provider_request_id=provider_id, cost_usd=str(cost),
                       elapsed_seconds=time.monotonic() - started, completed_at_utc=datetime.now(UTC).isoformat())
    except Exception as exc:
        receipt.update(status="uncertain", billing="unknown; no automatic retry", error_type=type(exc).__name__,
                       error_kind=getattr(exc, "kind", None), provider_request_id=getattr(exc, "provider_request_id", None),
                       elapsed_seconds=time.monotonic() - started, completed_at_utc=datetime.now(UTC).isoformat())
    replace_receipt(path, receipt)
    return {"id": packet["id"], "status": receipt["status"], "elapsed_seconds": receipt["elapsed_seconds"],
            "input_tokens": receipt.get("response", {}).get("usage", {}).get("input_tokens"),
            "cost_usd": receipt.get("cost_usd"), "error_kind": receipt.get("error_kind")}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", action="append", required=True, help="Frozen packet ID; repeat only for distinct IDs")
    parser.add_argument("--validate-only", action="store_true", help="Check source hashes, schemas and model windows without a provider call")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    manifest_hash = sha(MANIFEST.read_text())
    packets = {p["id"]: p for p in manifest["packets"]}
    if len(args.id) != len(set(args.id)) or any(i not in packets for i in args.id):
        raise SystemExit("IDs must be unique and present in the frozen manifest")
    if args.validate_only:
        for id_ in args.id:
            _, estimated_tokens = validate(packets[id_])
            print(json.dumps({"id": id_, "status": "validated", "estimated_input_tokens": estimated_tokens}))
        return
    # Resolve before marking any packet as attempted; this approved credential is never logged.
    api_key = resolve_typesafe_api_key()
    for id_ in args.id:
        result = await run_one(packets[id_], manifest_hash, api_key)
        print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
