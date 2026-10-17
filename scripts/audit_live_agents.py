"""Comprehensive Audit & Simulation of all 37 GoldScalper Agents."""

from __future__ import annotations

import asyncio
import json
import httpx
from datetime import UTC, datetime, timedelta

from agents.divisions import build_all_agents
from agents.state import SharedState, VOTE_BUY, VOTE_NEUTRAL, VOTE_SELL
from core.market_data import Candle, MarketDataCache
from config.settings import settings

AGENT_ROLES = {
    # TIMEFRAME
    "TF-M1-Sniper": "M1 trigger: micro rejection wick / immediate momentum",
    "TF-M5-Inspector": "M5 setup: displacement geometry (body >= 1.2x ATR)",
    "TF-M15-Liquidity": "M15 trend: dynamic EMA 20/50 + BSL/SSL pools",
    "TF-M30-Momentum": "M30 momentum: wick absorption / exhaustion",
    "TF-H1-Regime": "H1 regime: swing boxes + multi-bar chop detection",
    "TF-H4-Structure": "H4 structure: institutional order block touch",
    "TF-D1-Macro": "D1 macro: premium/discount extreme zone",
    "TF-DXY-Synthetic": "Synthetic DXY factor: USD strength inverse correlation",
    # STRUCTURE
    "Struct-MarketStructure": "BOS / CHoCH detection & swing HL/LH tracking",
    "Struct-Liquidity": "FVG, order blocks & liquidity sweeps",
    "Struct-Session": "Session trend scout, Anti-Waterfall & Anti-Rocket Vetoes",
    "Struct-Microstructure": "Order flow pressure from bar volume vs spread",
    "Struct-Correlation": "Cross-asset correlation: DXY, yields, silver",
    # TECHNICAL
    "Tech-Trend": "EMA 9/21 stack & slope direction",
    "Tech-Momentum": "RSI(14) + MACD histogram agreement",
    "Tech-Volatility": "ATR & Bollinger Bandwidth squeeze/expansion",
    "Tech-Volume": "Tick volume spikes (rvol >= 2.0)",
    "Tech-SupportResistance": "Swing pivots, Sideway Ping-Pong & Midline Veto",
    "Tech-Pattern": "Candlestick patterns: Engulfing, Hammer, Shooting Star",
    # FUNDAMENTAL
    "Fund-Calendar": "Economic calendar high-impact events & news blackout",
    "Fund-NewsSentiment": "News sentiment feed analysis (-1.0 to +1.0)",
    "Fund-MacroRegime": "Central bank policy stance (hawkish/dovish)",
    "Fund-Intermarket": "Macro intermarket score: DXY + US10Y + SPX",
    # RISK
    "Risk-PositionSizer": "Vol-adjusted fractional sizing & equity % calculation",
    "Risk-StopLoss": "ATR + structure based dynamic stop loss calculation",
    "Risk-TakeProfit": "R:R based take profit targets & partial scaling levels",
    "Risk-EntryTiming": "Market vs Limit entry timing & spread protection",
    "Risk-DrawdownGuard": "Daily/Weekly drawdown circuit breaker enforcement",
    "Risk-CostMonitor": "Spread, commission & slippage cost tracking",
    # SPK CORE
    "SPK-Chief": "Final trade GO/NO-GO authority & veto aggregation",
    "SPK-Aggregator": "Per-division weighted score aggregation",
    "SPK-Resolver": "HTF vs LTF timeframe conflict resolution",
    "SPK-Confidence": "Sigmoid-calibrated win probability estimation",
    "SPK-Tracker": "Per-agent historical win rate leaderboard tracker",
    # INFRA
    "Infra-Heartbeat": "Data freshness & tick/candle age staleness monitor",
    "Infra-Connectivity": "MT5 bridge, Redis, and Database reachability monitor",
    "Infra-Resource": "Cycle latency & error pressure monitor",
}

async def fetch_live_data():
    """Fetch live candles and quote from MT5 bridge using standard client."""
    from core.mt5_connector import create_client
    client = create_client(settings)
    await client.connect()
    
    quote = await client.symbol_tick(settings.mt5_symbol)
    frames = {}
    now = datetime.now(UTC)
    tf_lookbacks = {
        "M1": timedelta(hours=6),
        "M5": timedelta(hours=12),
        "M15": timedelta(hours=24),
        "M30": timedelta(hours=48),
        "H1": timedelta(days=5),
        "H4": timedelta(days=15),
        "D1": timedelta(days=30),
    }
    for tf, lookback in tf_lookbacks.items():
        try:
            candles = await client.copy_rates(settings.mt5_symbol, tf, now - lookback, now)
            frames[tf] = candles
        except Exception as e:
            pass
            
    from core.cross_asset import CrossAssetService
    suffix = "m" if settings.mt5_symbol.endswith("m") else ("c" if settings.mt5_symbol.endswith("c") else "")
    cross_srv = CrossAssetService(client, symbol_suffix=suffix)
    cross_data = await cross_srv.update(current_session="asia")
    
    await client.disconnect()
    return quote, frames, cross_data

async def run_audit():
    quote, frames, cross_data = await fetch_live_data()
    now_dt = datetime.now(UTC)
    
    bid = float(quote.bid) if quote else 4143.0
    ask = float(quote.ask) if quote else 4143.4
    spread_points = float(quote.spread * 10.0) if quote else 40.0
    
    from core.calendar_service import EconomicCalendarService
    cal = EconomicCalendarService()
    await cal.ensure_fresh()
    blackout, current_news = cal.check_blackout(now_dt)
    upcoming = cal.upcoming_events(now_dt, hours=12)
    
    from core.news_sentiment_service import NewsSentimentService
    ns = NewsSentimentService()
    await ns.ensure_fresh()
    sent_data = ns.get_state()
    
    extra_state = {
        "news_blackout": blackout,
        "current_news": current_news,
        "calendar_events": upcoming,
    }
    extra_state.update(cross_data)
    extra_state.update(sent_data)
    
    state = SharedState(
        symbol=settings.mt5_symbol,
        ts=now_dt,
        frames=frames,
        session="asia",
        bid=bid,
        ask=ask,
        spread_points=spread_points,
        equity=10000.0,
        balance=10000.0,
        extra=extra_state,
    )
    
    agents = build_all_agents()
    print(f"\nAUDIT 37 AGENT GOLDSOCALPER (LIVE STATE @ {now_dt.strftime('%H:%M:%S UTC')})")
    print(f"Price: Bid={bid:.2f}, Ask={ask:.2f}, Frames loaded: {list(frames.keys())}")
    print("=" * 135)
    print(f"{'AGENT ID':<24} | {'DIV':<10} | {'VOTE':<4} | {'CONF':<5} | {'VETO':<9} | {'STATUS':<15} | {'TUGAS & KONDISI AKTIF'}")
    print("-" * 135)
    
    counts = {"ACTIVE_VOTER": 0, "ACTIVE_VETOER": 0, "ACTIVE_PARAM": 0, "ACTIVE_DIAG": 0, "DORMANT_DATA": 0}
    
    for a in agents:
        sig = await a.evaluate(state)
        role = AGENT_ROLES.get(a.id, "Unknown agent")
        veto_str = sig.veto or "-"
        
        # Categorization logic
        if a.division in ("spk_core", "infra"):
            status = "DIAGNOSTIC"
            counts["ACTIVE_DIAG"] += 1
        elif a.division == "risk":
            status = "RISK_CALC"
            counts["ACTIVE_PARAM"] += 1
        elif a.id == "Fund-Calendar" and (sig.confidence > 0 or sig.veto):
            status = "ACTIVE MONITOR"
            counts["ACTIVE_VOTER"] += 1
        elif "missing" in (sig.reasoning or "").lower() or (sig.vote == 0 and sig.confidence == 0.0 and not sig.veto):
            status = "DORMANT (NO FEED)"
            counts["DORMANT_DATA"] += 1
        elif sig.veto:
            status = "ACTIVE VETOER"
            counts["ACTIVE_VETOER"] += 1
        else:
            status = "ACTIVE VOTER"
            counts["ACTIVE_VOTER"] += 1
            
        print(f"{a.id:<24} | {a.division:<10} | {sig.vote:>4} | {sig.confidence:>5.2f} | {veto_str:<9} | {status:<15} | {role} [{sig.reasoning}]")

    print("=" * 135)
    print(f"RINGKASAN STATUS AGENT:")
    print(f"1. Active Voting Agents       : {counts['ACTIVE_VOTER']}")
    print(f"2. Active Vetoing Agents      : {counts['ACTIVE_VETOER']}")
    print(f"3. Risk Parameter Calculators : {counts['ACTIVE_PARAM']}")
    print(f"4. Diagnostic & Health Monitor: {counts['ACTIVE_DIAG']}")
    print(f"5. DORMANT / PASIF (Tanpa Feed): {counts['DORMANT_DATA']}")
    print("=" * 135)

if __name__ == "__main__":
    asyncio.run(run_audit())
