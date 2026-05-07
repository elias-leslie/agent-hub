"""Generate a trading strategy configuration through Agent Hub agent routing.

Agent Hub owns the model and provider chain for the trade-manager agent. If the
agent call fails, this script falls back to deterministic strategy assembly.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path.home() / ".env.local")

from agent_hub import AsyncAgentHubClient  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from app.config import get_settings  # noqa: E402

PROJECT_ID = "portfolio-ai"
AGENT_SLUG = "trade-manager"
CLIENT_NAME = "agent-hub-trading-strategy"
REQUEST_SOURCE = "agent-hub-script"

# ---------------------------------------------------------------------------
# Full output Pydantic schema for the trading strategy config
# ---------------------------------------------------------------------------


class PositionSizing(BaseModel):
    recommended_allocation_pct: float = Field(
        description="Recommended portfolio allocation percentage (0-100)"
    )
    max_allocation_pct: float = Field(
        description="Maximum allowed portfolio allocation percentage (0-100)"
    )
    scaling_strategy: str = Field(
        description="How to scale into the position"
    )


class RiskManagement(BaseModel):
    stop_loss_pct: float = Field(description="Stop loss percentage below entry price")
    take_profit_pct: float = Field(description="Take profit percentage above entry price")
    max_drawdown_tolerance_pct: float = Field(
        description="Maximum acceptable drawdown from peak before reassessment"
    )


class TradingStrategyConfig(BaseModel):
    symbol: str = Field(description="Ticker symbol")
    as_of_date: str = Field(description="Date of the analysis (YYYY-MM-DD)")
    strategy_type: str = Field(description="Type of strategy")
    signal: Literal["buy", "sell", "hold", "reduce"] = Field(
        description="Primary trading signal"
    )
    conviction: Literal["low", "medium", "high"] = Field(
        description="Conviction level for the signal"
    )
    position_sizing: PositionSizing
    entry_conditions: list[str] = Field(
        description="Conditions for entering/adding to the position"
    )
    exit_conditions: list[str] = Field(
        description="Conditions that would trigger an exit or reduction"
    )
    risk_management: RiskManagement
    time_horizon: str = Field(description="Recommended holding period")
    key_risks: list[str] = Field(description="Key risks to monitor")
    key_catalysts: list[str] = Field(
        description="Key catalysts that could drive outperformance"
    )
    rationale: str = Field(description="Detailed rationale for the strategy recommendation")
    data_quality_notes: str = Field(
        description="Notes on data quality, confidence levels, and any caveats"
    )


# ---------------------------------------------------------------------------
# Minimal Pydantic schema for client.messages.parse() call
# (kept compact to fit within free-tier per-request token budget)
# ---------------------------------------------------------------------------


class CoreSignal(BaseModel):
    """Core trading parameters extracted via structured output (client.messages.parse)."""

    signal: Literal["buy", "sell", "hold", "reduce"]
    conviction: Literal["low", "medium", "high"]
    strategy_type: str
    stop_loss_pct: float
    take_profit_pct: float


# ---------------------------------------------------------------------------
# Research summary
# ---------------------------------------------------------------------------

RESEARCH_SUMMARY = {
    "symbol": "VTI",
    "as_of_date": "2026-03-17",
    "news": {
        "sentiment_trend": "stable",
        "sentiment_score": 0.6574764158576727,
        "sentiment_7d_avg": 0.0884061973572195,
        "sentiment_30d_avg": 0.00845356254809791,
        "material_events": ["acquisition", "product_launch", "earnings", "regulatory"],
        "news_volume": 716,
        "confidence": 1.0,
    },
    "fundamentals": {
        "company_health": "GOOD",
        "fundamental_score": 49,
        "valuation_tier": "overvalued",
        "growth_tier": "stable",
        "profitability_tier": "weak",
        "debt_tier": "moderate",
        "analyst_consensus": 3.0,
        "confidence": 0.0,
    },
    "technical": {
        "trend_strength": "neutral",
        "trend_duration_days": 0,
        "momentum_rating": "steady",
        "volume_profile": "stable",
        "rsi_zone": "healthy",
        "price_vs_ma": {"20d": 1.0, "50d": 1.0, "200d": 1.0},
        "confidence": 1.0,
    },
    "macro": {
        "market_regime": "range",
        "fear_greed_score": 13,
        "fear_greed_classification": "extreme_fear",
        "sector_rotation_phase": "recession",
    },
    "sector": {
        "sector": "Unknown",
        "sector_momentum": "in_line",
        "sector_vs_spy_30d": 0.0,
        "sector_rotation_signal": "hold",
    },
    "overall": {"confidence": 0.65, "quality": "medium"},
}


# ---------------------------------------------------------------------------
# Deterministic fallback — generates CoreSignal from research summary
# ---------------------------------------------------------------------------


def generate_core_signal_deterministic() -> CoreSignal:
    """
    Generate CoreSignal analytically from the research summary without API call.
    Used when API budget is exhausted.

    Analysis logic:
    - Extreme fear (13/100) = historically strong contrarian signal for eventual recovery
    - Overvalued + recession phase = near-term risk outweighs contrarian upside
    - Neutral technicals at all MAs = no momentum confirmation either direction
    - Overall: HOLD existing positions, reduce on any rally, DCA slowly on dips
    """
    macro = RESEARCH_SUMMARY["macro"]
    fundamentals = RESEARCH_SUMMARY["fundamentals"]
    fear = int(macro["fear_greed_score"])
    valuation = str(fundamentals["valuation_tier"])
    phase = str(macro["sector_rotation_phase"])

    # Signal determination: extreme fear + recession + overvalued = hold/reduce
    if fear <= 15 and valuation == "overvalued" and phase == "recession":
        signal = "hold"  # extreme fear is contrarian bullish, but other factors prevent reduce
        conviction = "medium"  # moderate confidence: fear=bullish, rest=bearish
        strategy_type = "defensive_accumulation"
    elif fear <= 15:
        signal = "hold"
        conviction = "medium"
        strategy_type = "defensive_hold"
    else:
        signal = "hold"
        conviction = "low"
        strategy_type = "defensive_hold"

    # Risk parameters: conservative given macro environment
    stop_loss_pct = 8.0  # 2x ATR typical for ETF
    take_profit_pct = 12.0  # realistic upside in range-bound market

    return CoreSignal(
        signal=signal,
        conviction=conviction,
        strategy_type=strategy_type,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------


_FALLBACK_ANALYSIS = (
    "VTI: HOLD with medium conviction. "
    "Extreme fear (13/100) is a contrarian signal but overvaluation and recession "
    "phase create near-term risk. Recommend defensive_accumulation via DCA on weakness. "
    "Primary risk: recession deepens, extending overvalued conditions through bear market."
)


def _agent_hub_base_url() -> str:
    settings = get_settings()
    return os.getenv("AGENT_HUB_URL") or f"http://127.0.0.1:{settings.port}"


def _agent_hub_client_id() -> str | None:
    settings = get_settings()
    return settings.portfolio_client_id or settings.agent_hub_dashboard_client_id or None


def _compact_research_context() -> str:
    rs = RESEARCH_SUMMARY
    return (
        f"VTI ({rs['as_of_date']}): "
        f"{rs['fundamentals']['valuation_tier']}, "
        f"fear={rs['macro']['fear_greed_score']} ({rs['macro']['fear_greed_classification']}), "
        f"{rs['macro']['sector_rotation_phase']} phase, "
        f"{rs['macro']['market_regime']} regime, "
        f"neutral trend, healthy RSI, price at all MAs (1.0x), "
        f"sentiment={rs['news']['sentiment_score']:.2f} stable."
    )


async def _stream_analysis(client: AsyncAgentHubClient, research_ctx: str) -> tuple[str, str, bool]:
    """Step 1: Ask the trade-manager agent for concise analysis."""
    print("\n[Step 1] Analysis via Agent Hub agent: trade-manager", file=sys.stderr)
    try:
        prompt = f"{research_ctx}\n1-2 sentence recommendation: trading signal (hold/reduce/buy/sell), conviction, primary risk. Be direct."
        response = await client.complete(
            agent_slug=AGENT_SLUG,
            project_id=PROJECT_ID,
            messages=[{"role": "user", "content": prompt}],
            purpose="trading_strategy_analysis",
            temperature=0.1,
            thinking_level="medium",
            use_memory=False,
        )
        analysis_text = response.content.strip()
        print(f"  Analysis: {analysis_text[:120]}...", file=sys.stderr)
        print(f"  Served model: {response.model}", file=sys.stderr)
        return analysis_text, response.model, True
    except Exception as exc:
        print(f"  [Agent call failed: {exc} — using fallback analysis]", file=sys.stderr)
        return _FALLBACK_ANALYSIS, f"agent:{AGENT_SLUG}", False


def _extract_json_object(content: str) -> dict[str, object] | None:
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(content[start:end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def _parse_core_signal(client: AsyncAgentHubClient, analysis_text: str) -> tuple[CoreSignal, str, bool]:
    """Step 2: Ask the agent for CoreSignal JSON and validate with Pydantic."""
    print("\n[Step 2] Structured CoreSignal via Agent Hub", file=sys.stderr)
    try:
        prompt = (
            "Return only a JSON object matching this schema: "
            '{"signal":"buy|sell|hold|reduce","conviction":"low|medium|high",'
            '"strategy_type":"string","stop_loss_pct":8.0,"take_profit_pct":12.0}.\n\n'
            f"VTI analysis: {analysis_text[:500]}"
        )
        response = await client.complete(
            agent_slug=AGENT_SLUG,
            project_id=PROJECT_ID,
            messages=[{"role": "user", "content": prompt}],
            purpose="trading_strategy_core_signal",
            temperature=0.1,
            thinking_level="medium",
            response_format={"type": "json_object"},
            use_memory=False,
        )
        payload = _extract_json_object(response.content)
        core = CoreSignal.model_validate(payload) if payload else None
        print(f"  Parsed: {core}", file=sys.stderr)
        print(f"  Served model: {response.model}", file=sys.stderr)
        return core or generate_core_signal_deterministic(), response.model, core is not None
    except Exception as exc:
        print(f"  [Structured agent call failed: {exc} — using deterministic fallback]", file=sys.stderr)
        core = generate_core_signal_deterministic()
        print(f"  Deterministic result: {core}", file=sys.stderr)
        return core, f"agent:{AGENT_SLUG}", False


def _api_status_label(model: str, stream_used: bool, parse_used: bool) -> str:
    if stream_used and parse_used:
        return f"Both streaming and parse() used live API calls to {model}."
    if stream_used:
        return f"Streaming analysis used live API call to {model}. parse() used deterministic fallback (API budget exhausted)."
    if parse_used:
        return f"parse() used live API call to {model}. Streaming analysis used deterministic fallback (API budget exhausted)."
    return f"Both steps used deterministic fallback analysis. Target route: {model}."


def _build_strategy_config(
    core: CoreSignal, model: str, stream_used_api: bool, parse_used_api: bool,
) -> TradingStrategyConfig:
    """Step 3: Assemble the full TradingStrategyConfig from research + core signal."""
    rs = RESEARCH_SUMMARY
    fear_score = rs["macro"]["fear_greed_score"]
    valuation = rs["fundamentals"]["valuation_tier"]
    sector_phase = rs["macro"]["sector_rotation_phase"]
    regime = rs["macro"]["market_regime"]
    fund_confidence = rs["fundamentals"]["confidence"]
    tech_confidence = rs["technical"]["confidence"]
    overall_confidence = rs["overall"]["confidence"]
    sentiment_score = rs["news"]["sentiment_score"]

    entry_conditions = [
        f"Fear & Greed Index drops below 10 (currently {fear_score}/100) — extreme capitulation historically precedes reversals",
        "Price pulls back 3-5% below current moving average cluster — improves entry relative to overvalued baseline",
        "Sector rotation signal shifts from 'hold' to 'buy' — confirms macro regime transition out of recession phase",
        "Weekly RSI moves toward oversold zone (<35) — technical confirmation layered onto sentiment extreme",
    ]
    exit_conditions = [
        "Fear & Greed Index recovers above 50 (neutral) — contrarian opportunity exhausted, reduce to target weight",
        f"Sector rotation exits {sector_phase} phase — macro tailwind fully priced, rebalance portfolio",
        f"Price extends >15% above all moving averages — mean reversion risk elevated given {valuation} baseline",
        f"Stop loss triggered at -{core.stop_loss_pct:.0f}% from entry — capital preservation rule, reassess thesis",
        "Fundamental confidence rises and confirms stretched valuation — shift from defensive to neutral stance",
    ]
    key_risks = [
        f"Recession deepens beyond current {sector_phase} phase — earnings contraction risk across VTI's broad US equity exposure",
        f"Overvaluation ({valuation}) persists through bear market — multiple compression and extended drawdown risk",
        f"Market regime transitions from {regime} to trending downward — technical breakdown through all moving averages",
        f"News sentiment reversal from current stable ({sentiment_score:.2f}) — 7d/30d averages near zero suggest fragile sentiment underpinning",
        "Federal Reserve policy error — extended restrictive conditions compress broad equity valuations",
        "Geopolitical escalation — risk-off rotation disproportionately affects US broad market exposure",
    ]
    key_catalysts = [
        f"Fear & Greed reversal from extreme ({fear_score}/100) — historically strong mean-reversion signal for broad US equities",
        "Federal Reserve rate cut cycle — multiple expansion benefit amplified by VTI's market-cap-weighted composition",
        f"Sector rotation exit from {sector_phase} to early-cycle — improves forward earnings outlook across VTI holdings",
        "Technical breakout above all moving averages (currently pinned at 1.0x) — momentum shift confirms macro recovery",
        f"Earnings beat cycle — analyst consensus at {rs['fundamentals']['analyst_consensus']:.1f}/5 leaves substantial room for positive revision",
        f"Material news events resolution (acquisitions, regulatory, earnings) from {rs['news']['news_volume']} active stories",
    ]
    api_status = _api_status_label(model, stream_used_api, parse_used_api)
    rationale = (
        f"VTI strategy: {core.signal} with {core.conviction} conviction as of {rs['as_of_date']}. "
        f"The extreme fear reading ({fear_score}/100) is a historically reliable contrarian signal, typically preceding market reversals. "
        f"However, the concurrent recession sector rotation phase and {valuation} valuations create asymmetric near-term risk. "
        f"Price pinned exactly at all key moving averages (20d/50d/200d all at 1.0x) signals technical indecision in a {regime}-bound regime. "
        f"Stable but shallow news sentiment (7d avg: {rs['news']['sentiment_7d_avg']:.3f}, 30d avg: {rs['news']['sentiment_30d_avg']:.4f}) provides no directional catalyst. "
        f"Strategy ({core.strategy_type}): maintain existing positions, accumulate modestly on fear-driven dips via DCA, avoid new lump-sum positions until macro regime shifts or technical breakout confirms recovery. "
        f"Risk-adjusted: {core.stop_loss_pct:.0f}% stop, {core.take_profit_pct:.0f}% target, overall research confidence {overall_confidence:.0%}."
    )
    data_quality_notes = (
        f"Overall research quality: {rs['overall']['quality']} (confidence: {overall_confidence:.0%}). "
        f"CAUTION: Fundamentals confidence = {fund_confidence:.0%} — standard fundamental metrics (valuation_tier, profitability_tier) have limited applicability to VTI as a broad index ETF; these aggregate underlying holdings rather than assess a single company. "
        f"Technical analysis confidence: {tech_confidence:.0%} (high reliability). "
        f"Sector = 'Unknown' by design — VTI spans all 11 GICS sectors. "
        f"Analyst consensus ({rs['fundamentals']['analyst_consensus']:.1f}/5) is not meaningful for ETFs. "
        f"API: {api_status}"
    )
    return TradingStrategyConfig(
        symbol=rs["symbol"], as_of_date=rs["as_of_date"],
        strategy_type=core.strategy_type, signal=core.signal, conviction=core.conviction,
        position_sizing=PositionSizing(recommended_allocation_pct=5.0, max_allocation_pct=8.0, scaling_strategy="dca_on_weakness"),
        entry_conditions=entry_conditions, exit_conditions=exit_conditions,
        risk_management=RiskManagement(stop_loss_pct=core.stop_loss_pct, take_profit_pct=core.take_profit_pct, max_drawdown_tolerance_pct=20.0),
        time_horizon="6-12 months", key_risks=key_risks, key_catalysts=key_catalysts,
        rationale=rationale, data_quality_notes=data_quality_notes,
    )


async def generate_trading_strategy() -> TradingStrategyConfig:
    print("Generating VTI trading strategy via Agent Hub agent: trade-manager", file=sys.stderr)
    async with AsyncAgentHubClient(
        base_url=_agent_hub_base_url(),
        client_name=CLIENT_NAME,
        client_id=_agent_hub_client_id(),
        request_source=REQUEST_SOURCE,
        cli_command="generate_trading_strategy",
    ) as client:
        research_ctx = _compact_research_context()
        analysis_text, analysis_model, stream_used_api = await _stream_analysis(client, research_ctx)
        core, parse_model, parse_used_api = await _parse_core_signal(client, analysis_text)

    print("\n[Step 3] Assembling full TradingStrategyConfig...", file=sys.stderr)
    served_route = parse_model if parse_used_api else analysis_model
    return _build_strategy_config(core, served_route, stream_used_api, parse_used_api)


async def main():
    strategy = await generate_trading_strategy()
    print(json.dumps(strategy.model_dump(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
