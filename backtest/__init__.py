"""Backtesting: replay historical candles through the live agent stack."""

from __future__ import annotations

from backtest.engine import BacktestEngine, BacktestResult, load_history_from_repo
from backtest.metrics import compute_stats, format_stats, max_drawdown
from backtest.sim_broker import SimBroker

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "SimBroker",
    "compute_stats",
    "format_stats",
    "max_drawdown",
    "load_history_from_repo",
]
