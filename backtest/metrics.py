"""Backtest performance metrics."""

from __future__ import annotations

from typing import Any


def max_drawdown(equity: list[float], initial: float) -> float:
    """Largest peak-to-trough decline, as a fraction of the running peak."""
    peak = initial
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def compute_stats(
    realized: list[dict[str, Any]],
    equity_curve: list[float],
    initial_balance: float,
) -> dict[str, Any]:
    """Aggregate realized fills + equity curve into a stats dict."""
    pnls = [float(t.get("pnl", 0.0)) for t in realized]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    total = sum(pnls)
    n = len(pnls)

    final = equity_curve[-1] if equity_curve else initial_balance
    peak_equity = max(equity_curve) if equity_curve else initial_balance

    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "winrate": round(len(wins) / n, 4) if n else 0.0,
        "total_pnl": round(total, 2),
        "gross_win": round(gross_win, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "avg_win": round(gross_win / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
        "expectancy": round(total / n, 3) if n else 0.0,
        "net_return_pct": round(100.0 * total / initial_balance, 3) if initial_balance else 0.0,
        "max_drawdown_pct": round(100.0 * max_drawdown(equity_curve, initial_balance), 3),
        "peak_equity": round(peak_equity, 2),
        "final_equity": round(final, 2),
    }


def format_stats(stats: dict[str, Any]) -> str:
    return (
        f"trades={stats['trades']} winrate={stats['winrate']} "
        f"pnl={stats['total_pnl']} pf={stats['profit_factor']} "
        f"expectancy={stats['expectancy']} "
        f"return={stats['net_return_pct']}% maxDD={stats['max_drawdown_pct']}%"
    )


__all__ = ["compute_stats", "max_drawdown", "format_stats"]
