"""HTTP fetchers for external benchmark/pricing data sources."""

from __future__ import annotations

import csv
import io
from typing import Any

import httpx

MODELS_DEV_URL = "https://models.dev/api.json"
BENCHMARKS_URL = "https://cdn.jsdelivr.net/gh/arimxyer/models@main/data/benchmarks.json"
BFCL_URL = "https://raw.githubusercontent.com/HuanzhiMao/BFCL-Result/main/2025-12-16/score/data_overall.csv"
LIVEBENCH_URL = "https://raw.githubusercontent.com/LiveBench/livebench.github.io/main/public/table_2026_01_08.csv"

_HTTP_TIMEOUT = 30.0


async def fetch_models_dev() -> list[dict[str, Any]]:
    """Fetch model catalog from models.dev API."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(MODELS_DEV_URL)
        resp.raise_for_status()
        data = resp.json()

    if isinstance(data, list):
        return data

    flat: list[dict[str, Any]] = []
    for provider_id, provider_data in data.items():
        if not isinstance(provider_data, dict):
            continue
        provider_name = provider_data.get("name", provider_id)
        models = provider_data.get("models", {})
        if not isinstance(models, dict):
            continue
        for model_id, model_data in models.items():
            if isinstance(model_data, dict):
                model_data.setdefault("id", model_id)
                model_data.setdefault("provider_id", provider_id)
                model_data.setdefault("provider_name", provider_name)
                flat.append(model_data)
    return flat


async def fetch_benchmarks() -> list[dict[str, Any]]:
    """Fetch benchmark data from arimxyer/models (jsdelivr CDN)."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(BENCHMARKS_URL)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("benchmarks", data.get("data", []))


async def fetch_bfcl() -> list[dict[str, Any]]:
    """Fetch BFCL (Berkeley Function Calling Leaderboard) data.

    Returns list of dicts with keys: Model, Overall Acc, Organization, etc.
    """
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(BFCL_URL)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        return list(reader)


async def fetch_livebench() -> list[dict[str, Any]]:
    """Fetch LiveBench task-level scores.

    Returns list of dicts with keys: model, AMPS_Hard, code_completion, etc.
    """
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(LIVEBENCH_URL)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        return list(reader)
