"""Retired experiment APIs have no registered handlers or compatibility stubs."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.api import router
from app.config import settings
from app.models.base import Base


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [
    ("GET", "/api/neri/local-worker/status"),
    ("POST", "/api/neri/local-worker/evaluate"),
    ("POST", "/api/neri/local-worker/benchmarks"),
    ("POST", "/api/neri/jev/evaluate"),
])
async def test_retired_experiment_routes_are_absent(method: str, path: str) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, json={})
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert path not in app.openapi()["paths"]


def test_generic_model_administration_and_completions_remain_registered() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    paths = app.openapi()["paths"]
    assert "/api/models" in paths
    assert "/api/complete" in paths


def test_retired_runtime_service_config_and_active_models_are_absent() -> None:
    root = Path(__file__).resolve().parents[3]
    identity = json.loads((root / "project.identity.json").read_text())
    assert "agent-hub-neri-local-qwen.service" not in identity["services"]["optional_workers"]
    for relative in (
        "backend/app/llm/runtime_profiles.py", "backend/scripts/run_neri_local_qwen.py",
        "scripts/systemd/agent-hub-neri-local-qwen.service",
        "backend/app/services/neri_local_worker.py", "backend/app/services/neri_local_worker_benchmark.py",
        "backend/app/services/neri_local_worker_study.py", "backend/app/models/typesafe_jev.py",
    ):
        assert not (root / relative).exists()
    assert "neri_local_qwen_base_url" not in type(settings).model_fields
    assert "typesafe_jev_budgets" not in Base.metadata.tables
    assert "typesafe_jev_dispatches" not in Base.metadata.tables
