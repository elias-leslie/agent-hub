"""Committee roundtable execution service."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.complete.complete_orchestrator import orchestrate_completion
from app.api.complete.schemas import (
    CompletionRequest,
    CompletionResponse,
    MessageInput,
    ResponseFormat,
)
from app.api.orchestration_models import (
    CommitteeConfig,
    CommitteeOrchestratorConfig,
    CommitteeRoundtableRequest,
    CommitteeSeatConfig,
)
from app.db import async_session
from app.services.agent_service import get_agent_service

DEFAULT_COMMITTEE_CONFIG = CommitteeConfig(
    orchestrator=CommitteeOrchestratorConfig(
        agent_slug="investment-committee",
        model_id="codex/gpt-5.4",
        instruction="Synthesize committee votes into the final market call.",
    ),
    seats=[
        CommitteeSeatConfig(
            key="macro",
            label="Macro",
            enabled=True,
            agent_slug="market-pulse-analyst",
            model_id="codex/gpt-5.4",
            instruction="Focus on macro regime, rates, breadth, and options positioning.",
            weight=1.0,
        ),
        CommitteeSeatConfig(
            key="cross_asset",
            label="Cross-Asset",
            enabled=True,
            agent_slug="equity-analyst",
            model_id="xai/grok-4.20-reasoning",
            instruction="Stress-test cross-asset leadership, policy shocks, and narrative drift.",
            weight=1.0,
        ),
        CommitteeSeatConfig(
            key="risk",
            label="Risk",
            enabled=True,
            agent_slug="risk-manager",
            model_id="claude-opus-4-7",
            instruction="Challenge downside tails, uncertainty, and failure modes.",
            weight=1.0,
        ),
    ],
)


class CommitteeRoundtableService:
    async def run_roundtable(
        self,
        request: CommitteeRoundtableRequest,
        http_request: Request,
        db: AsyncSession | None,
    ) -> dict[str, Any]:
        config = await self._resolve_committee_config(request.agent_slug, db)
        source_snapshot = self._normalize_snapshot(request.source_snapshot)
        symbols = request.symbols or source_snapshot.get("target_universe") or ["SPY"]
        symbols = [str(symbol).upper() for symbol in symbols]

        seat_votes_nested = await asyncio.gather(
            *[
                self._run_seat(
                    seat=seat,
                    request=request,
                    http_request=http_request,
                    db=db,
                    symbols=symbols,
                    source_snapshot=source_snapshot,
                )
                for seat in config.seats
                if seat.enabled
            ]
        )
        votes = [vote for group in seat_votes_nested for vote in group]
        calls = self._aggregate_calls(votes, symbols)
        committee_summary = self._default_summary(votes, calls)

        orchestrator_payload = await self._run_orchestrator(
            config=config,
            request=request,
            http_request=http_request,
            db=db,
            symbols=symbols,
            source_snapshot=source_snapshot,
            votes=votes,
            calls=calls,
        )
        if isinstance(orchestrator_payload.get("committee_summary"), dict):
            committee_summary = orchestrator_payload["committee_summary"]
        override_calls = orchestrator_payload.get("calls")
        if isinstance(override_calls, list) and override_calls:
            calls = self._merge_orchestrator_calls(calls, override_calls, symbols)

        return {
            "agent_slug": request.agent_slug,
            "committee_config": config.model_dump(),
            "committee_summary": committee_summary,
            "calls": calls,
            "votes": votes,
        }

    async def _resolve_committee_config(
        self,
        agent_slug: str,
        db: AsyncSession | None,
    ) -> CommitteeConfig:
        if db is None:
            return DEFAULT_COMMITTEE_CONFIG.model_copy(deep=True)
        agent = await get_agent_service().get_by_slug(db, agent_slug, active_only=False)
        if agent is None or not isinstance(agent.strategies, dict):
            return DEFAULT_COMMITTEE_CONFIG.model_copy(deep=True)
        raw_committee = agent.strategies.get("committee")
        if not isinstance(raw_committee, dict):
            return DEFAULT_COMMITTEE_CONFIG.model_copy(deep=True)
        try:
            return CommitteeConfig.model_validate(raw_committee)
        except Exception:
            return DEFAULT_COMMITTEE_CONFIG.model_copy(deep=True)

    async def _run_seat(
        self,
        *,
        seat: CommitteeSeatConfig,
        request: CommitteeRoundtableRequest,
        http_request: Request,
        db: AsyncSession | None,
        symbols: list[str],
        source_snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        prompt = (
            f"You are the {seat.label} seat on the Market Prediction Committee. "
            f"Window: {request.window_days} trading days. Symbols: {', '.join(symbols)}. "
            "Return JSON only with keys seat_summary and predictions. Each prediction must include "
            "symbol, direction_label, prob_up, expected_move_pct, confidence_score, rationale_summary, and source_clusters. "
            f"Seat instruction: {seat.instruction or 'Use your specialty to assess the market call.'}\n\n"
            f"User prompt:\n{request.prompt}\n\n"
            f"Source snapshot JSON:\n{json.dumps(source_snapshot, default=str)}"
        )
        payload = await self._run_json_completion(
            agent_slug=seat.agent_slug,
            model_id=seat.model_id,
            prompt=prompt,
            project_id=request.project_id,
            http_request=http_request,
            db=db,
            trace_id=request.trace_id,
            external_id=request.external_id,
        )
        predictions = payload.get("predictions") if isinstance(payload, dict) else []
        if not isinstance(predictions, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in predictions:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").upper()
            if symbol not in symbols:
                continue
            prob_up = self._clamp(item.get("prob_up"), 0.5, low=0.0, high=1.0)
            expected_move_pct = self._clamp(item.get("expected_move_pct"), 0.0, low=-100.0, high=100.0)
            normalized.append(
                {
                    "seat_key": seat.key,
                    "agent_slug": seat.agent_slug,
                    "model_id": seat.model_id,
                    "provider": str(payload.get("provider") or self._provider_from_model(seat.model_id)),
                    "symbol": symbol,
                    "window_days": request.window_days,
                    "direction_label": self._direction(item.get("direction_label"), prob_up, expected_move_pct),
                    "prob_up": prob_up,
                    "expected_move_pct": expected_move_pct,
                    "confidence_score": self._clamp(item.get("confidence_score"), 50.0, low=0.0, high=100.0),
                    "rationale_summary": str(item.get("rationale_summary") or item.get("thesis") or "").strip() or None,
                    "source_clusters": self._normalize_clusters(item.get("source_clusters")),
                    "weight": seat.weight,
                }
            )
        return normalized

    async def _run_orchestrator(
        self,
        *,
        config: CommitteeConfig,
        request: CommitteeRoundtableRequest,
        http_request: Request,
        db: AsyncSession | None,
        symbols: list[str],
        source_snapshot: dict[str, Any],
        votes: list[dict[str, Any]],
        calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt = (
            "Synthesize these committee seat votes into the final market prediction committee output. "
            "Return JSON only with keys committee_summary and calls. Each call must include symbol, direction_label, prob_up, "
            "expected_move_pct, confidence_band_low_pct, confidence_band_high_pct, confidence_score, committee_disagreement_score, rationale_summary, and top_source_clusters.\n\n"
            f"Committee instruction: {config.orchestrator.instruction or 'Produce the final committee synthesis.'}\n\n"
            f"User prompt:\n{request.prompt}\n\n"
            f"Symbols: {', '.join(symbols)}\n\n"
            f"Source snapshot JSON:\n{json.dumps(source_snapshot, default=str)}\n\n"
            f"Seat votes JSON:\n{json.dumps(votes, default=str)}\n\n"
            f"Aggregated calls JSON:\n{json.dumps(calls, default=str)}"
        )
        return await self._run_json_completion(
            agent_slug=config.orchestrator.agent_slug,
            model_id=config.orchestrator.model_id,
            prompt=prompt,
            project_id=request.project_id,
            http_request=http_request,
            db=db,
            trace_id=request.trace_id,
            external_id=request.external_id,
        )

    async def _run_json_completion(
        self,
        *,
        agent_slug: str,
        model_id: str | None,
        prompt: str,
        project_id: str,
        http_request: Request,
        db: AsyncSession | None,
        trace_id: str | None,
        external_id: str | None,
    ) -> dict[str, Any]:
        completion_request = CompletionRequest(
            model=model_id,
            agent_slug=agent_slug,
            messages=[MessageInput(role="user", content=prompt)],
            project_id=project_id,
            use_memory=False,
            response_format=ResponseFormat(type="json_object"),
            max_turns=1,
            execute_tools=False,
            trace_id=trace_id,
            external_id=external_id,
        )
        async with async_session() as completion_db:
            response = await orchestrate_completion(
                completion_request,
                http_request,
                False,
                completion_db,
            )
        if not isinstance(response, CompletionResponse):
            return {}
        payload = self._parse_json_object(response.content)
        if isinstance(payload, dict):
            payload.setdefault("model", response.model)
            payload.setdefault("provider", response.provider)
            return payload
        return {}

    def _aggregate_calls(self, votes: list[dict[str, Any]], symbols: list[str]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
        for vote in votes:
            grouped.setdefault(str(vote["symbol"]), []).append(vote)

        calls: list[dict[str, Any]] = []
        for symbol in symbols:
            symbol_votes = grouped.get(symbol, [])
            if not symbol_votes:
                calls.append(
                    {
                        "symbol": symbol,
                        "window_days": 0,
                        "direction_label": "neutral",
                        "prob_up": 0.5,
                        "expected_move_pct": 0.0,
                        "confidence_score": 0.0,
                        "committee_disagreement_score": 1.0,
                        "rationale_summary": "No seat votes available.",
                        "top_source_clusters": [],
                    }
                )
                continue
            weight_sum = sum(float(vote.get("weight") or 1.0) for vote in symbol_votes) or 1.0
            avg_prob = sum(float(vote["prob_up"]) * float(vote.get("weight") or 1.0) for vote in symbol_votes) / weight_sum
            avg_move = sum(float(vote["expected_move_pct"]) * float(vote.get("weight") or 1.0) for vote in symbol_votes) / weight_sum
            avg_conf = sum(float(vote.get("confidence_score") or 50.0) * float(vote.get("weight") or 1.0) for vote in symbol_votes) / weight_sum
            low = min(float(vote["expected_move_pct"]) for vote in symbol_votes)
            high = max(float(vote["expected_move_pct"]) for vote in symbol_votes)
            calls.append(
                {
                    "symbol": symbol,
                    "window_days": int(symbol_votes[0]["window_days"]),
                    "direction_label": self._direction(None, avg_prob, avg_move),
                    "prob_up": avg_prob,
                    "expected_move_pct": avg_move,
                    "confidence_band_low_pct": low,
                    "confidence_band_high_pct": high,
                    "confidence_score": avg_conf,
                    "committee_disagreement_score": max(float(vote["prob_up"]) for vote in symbol_votes) - min(float(vote["prob_up"]) for vote in symbol_votes),
                    "rationale_summary": "Consensus synthesized from seat-level votes.",
                    "top_source_clusters": self._merge_clusters(symbol_votes),
                }
            )
        return calls

    def _merge_orchestrator_calls(
        self,
        base_calls: list[dict[str, Any]],
        override_calls: list[dict[str, Any]],
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        call_map = {str(call["symbol"]): dict(call) for call in base_calls}
        for raw in override_calls:
            if not isinstance(raw, dict):
                continue
            symbol = str(raw.get("symbol") or "").upper()
            if symbol not in symbols:
                continue
            existing = call_map.get(symbol, {})
            prob_up = self._clamp(raw.get("prob_up"), float(existing.get("prob_up", 0.5)), low=0.0, high=1.0)
            expected_move_pct = self._clamp(raw.get("expected_move_pct"), float(existing.get("expected_move_pct", 0.0)), low=-100.0, high=100.0)
            existing.update(
                {
                    "symbol": symbol,
                    "window_days": int(raw.get("window_days") or existing.get("window_days") or 0),
                    "direction_label": self._direction(raw.get("direction_label"), prob_up, expected_move_pct),
                    "prob_up": prob_up,
                    "expected_move_pct": expected_move_pct,
                    "confidence_band_low_pct": self._optional_float(raw.get("confidence_band_low_pct"), existing.get("confidence_band_low_pct")),
                    "confidence_band_high_pct": self._optional_float(raw.get("confidence_band_high_pct"), existing.get("confidence_band_high_pct")),
                    "confidence_score": self._clamp(raw.get("confidence_score"), float(existing.get("confidence_score", 50.0)), low=0.0, high=100.0),
                    "committee_disagreement_score": self._clamp(raw.get("committee_disagreement_score"), float(existing.get("committee_disagreement_score", 0.0)), low=0.0, high=1.0),
                    "rationale_summary": str(raw.get("rationale_summary") or existing.get("rationale_summary") or "").strip() or None,
                    "top_source_clusters": self._normalize_clusters(raw.get("top_source_clusters")) or existing.get("top_source_clusters", []),
                }
            )
            call_map[symbol] = existing
        return [call_map[symbol] for symbol in symbols if symbol in call_map]

    def _default_summary(self, votes: list[dict[str, Any]], calls: list[dict[str, Any]]) -> dict[str, Any]:
        spy_call = next((call for call in calls if call.get("symbol") == "SPY"), calls[0] if calls else None)
        disagreement = float(spy_call.get("committee_disagreement_score", 0.0)) if spy_call else 0.0
        label = "high" if disagreement >= 0.67 else "moderate" if disagreement >= 0.34 else "low"
        direction = str(spy_call.get("direction_label") if spy_call else "neutral")
        return {
            "headline": f"{direction.title()} committee bias with {label} disagreement.",
            "seat_count": len({vote["seat_key"] for vote in votes}),
            "disagreement_label": label,
        }

    def _merge_clusters(self, votes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        totals: dict[str, float] = {}
        for vote in votes:
            for cluster in vote.get("source_clusters", []):
                if not isinstance(cluster, dict):
                    continue
                key = str(cluster.get("cluster") or "")
                if not key:
                    continue
                totals[key] = totals.get(key, 0.0) + float(cluster.get("weight") or 0.0)
        return [
            {"cluster": key, "weight": value}
            for key, value in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:3]
        ]

    def _normalize_clusters(self, raw_clusters: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_clusters, list):
            return []
        clusters: list[dict[str, Any]] = []
        for raw in raw_clusters[:5]:
            if not isinstance(raw, dict):
                continue
            cluster = str(raw.get("cluster") or "").strip()
            if not cluster:
                continue
            clusters.append(
                {
                    "cluster": cluster,
                    "weight": self._optional_float(raw.get("weight"), None),
                    "freshness": raw.get("freshness"),
                    "note": raw.get("note"),
                }
            )
        return clusters

    def _normalize_snapshot(self, source_snapshot: dict[str, Any] | str) -> dict[str, Any]:
        if isinstance(source_snapshot, dict):
            return source_snapshot
        if isinstance(source_snapshot, str):
            try:
                parsed = json.loads(source_snapshot)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _parse_json_object(self, content: str) -> dict[str, Any] | None:
        text = (content or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            if "{" not in text or "}" not in text:
                return None
            start = text.find("{")
            end = text.rfind("}")
            try:
                parsed = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None

    def _direction(self, explicit: Any, prob_up: float, expected_move_pct: float) -> str:
        explicit_text = str(explicit or "").strip().lower()
        if explicit_text in {"bullish", "neutral", "bearish"}:
            return explicit_text
        if prob_up >= 0.55 and expected_move_pct > 0:
            return "bullish"
        if prob_up <= 0.45 and expected_move_pct < 0:
            return "bearish"
        return "neutral"

    def _provider_from_model(self, model_id: str | None) -> str | None:
        if not model_id:
            return None
        if "/" in model_id:
            return model_id.split("/", 1)[0]
        if model_id.startswith("claude"):
            return "claude"
        return None

    def _clamp(self, value: Any, fallback: float, *, low: float, high: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = fallback
        return max(low, min(high, numeric))

    def _optional_float(self, value: Any, fallback: Any) -> float | Any:
        try:
            return fallback if value is None else float(value)
        except (TypeError, ValueError):
            return fallback
