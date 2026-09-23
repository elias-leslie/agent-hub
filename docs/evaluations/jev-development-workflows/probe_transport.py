"""No-provider transport failures; one mocked request per condition."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.typesafe_jev_schemas import ChoiceQuestion, SystemOneRequest  # noqa: E402
from app.services.typesafe_jev import TypeSafeJevError, call_typesafe_jev  # noqa: E402


REQUEST = SystemOneRequest(
    model="jev-1.13.0",
    state={"claim": "A check passed", "checks": []},
    questions={"status": ChoiceQuestion(
        type="choice",
        instructions="Classify this claim from the supplied evidence.",
        criteria={"supported": "Evidence demonstrates it", "unknown": "Evidence is missing"},
    )},
)


async def one_case(name: str) -> dict[str, object]:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if name == "timeout":
            raise httpx.ReadTimeout("mock provider timeout", request=request)
        if name == "unavailable_model":
            return httpx.Response(404, text="model unavailable")
        return httpx.Response(200, text="not JSON")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        try:
            await call_typesafe_jev(REQUEST, api_key="fixture-only", http_client=client)
        except TypeSafeJevError as exc:
            return {"condition": name, "calls": calls, "error_kind": exc.kind, "result": "not_evaluated"}
        except httpx.ReadTimeout:
            return {"condition": name, "calls": calls, "error_kind": "transport_timeout", "result": "not_evaluated"}
    raise AssertionError(f"{name}: failure was silently accepted")


async def main() -> None:
    results = [await one_case(name) for name in ("timeout", "unavailable_model", "malformed_response")]
    assert all(item["calls"] == 1 and item["result"] == "not_evaluated" for item in results)
    print(json.dumps({"kind": "mocked_transport", "cases": results}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
