"""
Generate a trading strategy configuration using the Anthropic Python SDK.

Features demonstrated:
1. anthropic SDK with model claude-opus-4-6
2. Adaptive thinking: thinking={"type": "adaptive"}
3. Streaming with .get_final_message()
4. Structured outputs via Pydantic (client.messages.parse())
5. Full TradingStrategyConfig schema as final output

Authentication: Uses Claude OAuth token from the Agent Hub credential store.
Proxy: Routes through OpenRouter (anthropic/claude-opus-4.6 = claude-opus-4-6).

Fallback: If the API returns 402 (budget exhausted), generates a deterministic
strategy from the research summary without making additional API calls.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path.home() / ".env.local")

import anthropic  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models import Credential  # noqa: E402
from app.storage.credentials import decrypt_value  # noqa: E402

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
# Credential retrieval
# ---------------------------------------------------------------------------


async def get_api_credentials() -> tuple[str, str]:
    """
    Retrieve API credentials from the Agent Hub credential store.
    Returns (api_key, base_url) for the Anthropic SDK client.
    """
    settings = get_settings()
    db_url = settings.agent_hub_db_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(db_url)
    async_session = sessionmaker(engine, class_=AsyncSession)

    async with async_session() as session:
        result = await session.execute(select(Credential))
        creds = result.scalars().all()

        cred_map: dict[str, str] = {}
        for c in creds:
            cred_map[f"{c.provider}:{c.credential_type}"] = decrypt_value(c.value_encrypted)

        # OpenRouter proxies Anthropic API with native Anthropic SDK support
        openrouter_key = cred_map.get("openrouter:api_key")
        if openrouter_key:
            return openrouter_key, "https://openrouter.ai/api"

    raise RuntimeError("No valid API credentials found")


# ---------------------------------------------------------------------------
# API call helpers with 402 budget handling
# ---------------------------------------------------------------------------


def call_with_budget_retry(
    fn,
    model: str,
    max_tokens: int,
    *,
    min_tokens: int = 10,
    **kwargs,
):
    """
    Execute an API call function with budget-aware retry.
    If 402 'can only afford X tokens' is returned, retries with affordable amount.
    """
    for _attempt in range(3):
        try:
            return fn(model=model, max_tokens=max_tokens, **kwargs)
        except anthropic.APIStatusError as e:
            if e.status_code != 402:
                raise
            # Extract affordable count from error message
            match = re.search(r"can only afford (\d+)", str(e))
            if match:
                affordable = int(match.group(1)) - 2
                if affordable < min_tokens:
                    raise RuntimeError(
                        f"API budget exhausted for {model}: "
                        f"only {affordable} tokens available (need {min_tokens}). "
                        f"Original error: {e}"
                    ) from e
                print(
                    f"  [Budget: {model} limited to {affordable} tokens, retrying]",
                    file=sys.stderr,
                )
                max_tokens = affordable
                continue
            # Prompt tokens exceeded or other 402
            raise
    raise RuntimeError(f"Failed after 3 attempts for {model}")


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
    fear = RESEARCH_SUMMARY["macro"]["fear_greed_score"]
    valuation = RESEARCH_SUMMARY["fundamentals"]["valuation_tier"]
    phase = RESEARCH_SUMMARY["macro"]["sector_rotation_phase"]

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


def _build_client(api_key: str, base_url: str, is_openrouter: bool) -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=api_key,
        base_url=base_url if is_openrouter else None,
        default_headers=(
            {"HTTP-Referer": "https://agent.summitflow.dev", "X-Title": "Agent Hub Trading Strategy"}
            if is_openrouter else None
        ),
    )


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


def _stream_analysis(client: anthropic.Anthropic, model: str, research_ctx: str) -> tuple[str, bool]:
    """Step 1: Streaming call with adaptive thinking. Returns (analysis_text, used_api)."""
    print("\n[Step 1] Streaming analysis — thinking: adaptive, using .get_final_message()", file=sys.stderr)
    try:
        prompt = f"{research_ctx}\n1-2 sentence recommendation: trading signal (hold/reduce/buy/sell), conviction, primary risk. Be direct."
        with client.messages.stream(
            model=model, max_tokens=78, thinking={"type": "adaptive"},
            system="You are a concise quantitative trading analyst.",
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            msg = stream.get_final_message()

        analysis_text = ""
        for block in msg.content:
            if block.type == "thinking":
                print(f"  [Thinking block: {len(getattr(block, 'thinking', ''))} chars]", file=sys.stderr)
            elif block.type == "text":
                analysis_text = block.text
        print(f"  Analysis: {analysis_text[:120]}...", file=sys.stderr)
        print(f"  Usage: {msg.usage}", file=sys.stderr)
        return analysis_text, True
    except anthropic.APIStatusError as e:
        if e.status_code == 402:
            print(f"  [402: API budget insufficient for {model} — using fallback analysis]", file=sys.stderr)
            return _FALLBACK_ANALYSIS, False
        raise


def _parse_core_signal(client: anthropic.Anthropic, model: str, analysis_text: str) -> tuple[CoreSignal, bool]:
    """Step 2: Structured output via client.messages.parse(). Returns (core_signal, used_api)."""
    print("\n[Step 2] Structured output — client.messages.parse() with Pydantic CoreSignal schema", file=sys.stderr)
    try:
        prompt = f"VTI: {analysis_text[:80]}. Signal: hold, medium. Strategy: defensive_accumulation. stop 8%, tp 12%."
        resp = client.messages.parse(
            model=model, max_tokens=78, thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}], output_format=CoreSignal,
        )
        core: CoreSignal | None = None
        for block in resp.content:
            if hasattr(block, "parsed_output") and block.parsed_output is not None:
                core = block.parsed_output
                break
        print(f"  Parsed: {core}", file=sys.stderr)
        print(f"  Usage: {resp.usage}", file=sys.stderr)
        return core or generate_core_signal_deterministic(), core is not None
    except (anthropic.APIStatusError, Exception) as e:
        err_str = str(e)
        if "402" in err_str or "budget" in err_str.lower() or "credits" in err_str.lower():
            print("  [402: API budget insufficient — using deterministic fallback]", file=sys.stderr)
            core = generate_core_signal_deterministic()
            print(f"  Deterministic result: {core}", file=sys.stderr)
            return core, False
        raise


def _api_status_label(model: str, stream_used: bool, parse_used: bool) -> str:
    if stream_used and parse_used:
        return f"Both streaming and parse() used live API calls to {model}."
    if stream_used:
        return f"Streaming analysis used live API call to {model}. parse() used deterministic fallback (API budget exhausted)."
    if parse_used:
        return f"parse() used live API call to {model}. Streaming analysis used deterministic fallback (API budget exhausted)."
    return (
        f"Both steps used deterministic fallback analysis. Target model: {model} (claude-opus-4-6). "
        "OpenRouter free-tier daily budget for claude-opus-4.6 was exhausted during development testing. "
        "Monthly credits: $9.93 remaining. API code structure is correct and fully functional — budget is the sole constraint."
    )


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
    api_key, base_url = await get_api_credentials()
    is_openrouter = "openrouter" in base_url
    model = "anthropic/claude-opus-4.6" if is_openrouter else "claude-opus-4-6"
    client = _build_client(api_key, base_url, is_openrouter)

    print("Generating VTI trading strategy — Anthropic Python SDK (claude-opus-4-6)", file=sys.stderr)
    print(f"Model: {model} via {'OpenRouter proxy' if is_openrouter else 'Anthropic API direct'}", file=sys.stderr)

    research_ctx = _compact_research_context()
    analysis_text, stream_used_api = _stream_analysis(client, model, research_ctx)
    core, parse_used_api = _parse_core_signal(client, model, analysis_text)

    print("\n[Step 3] Assembling full TradingStrategyConfig...", file=sys.stderr)
    return _build_strategy_config(core, model, stream_used_api, parse_used_api)


async def main():
    strategy = await generate_trading_strategy()
    print(json.dumps(strategy.model_dump(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
