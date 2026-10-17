# GoldScalper

Multi-agent AI scalping system for **XAUUSD (Gold)** — M1 fast in/out with an
agent-consensus decision engine (SPK) and an adaptive learning loop.

> **Workstation Note:** Workstation Windows PC dialokasikan **khusus untuk aplikasi `AcengGold`**. Seluruh infrastruktur GoldScalper (Core Bot, TimescaleDB, Redis, dan MetaTrader 5 Wine container) berjalan mandiri 24/7 di **Home-Server (`100.114.150.48`)**.

## Documentation

| Doc | Purpose |
|-----|---------|
| [`docs/PRD.md`](docs/PRD.md) | Product requirements |
| [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md) | Technical architecture (100% Home-Server) |
| [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) | Phased task plan |
| [`docs/PROGRESS.md`](docs/PROGRESS.md) | Worklog — riwayat update pekerjaan |
| [`docs/DEPLOYMENT_SOP.md`](docs/DEPLOYMENT_SOP.md) | Deployment SOP (100% Home-Server) |
| [`docs/DEPLOYMENT_SOP_WINDOWS_BRIDGE.md`](docs/DEPLOYMENT_SOP_WINDOWS_BRIDGE.md) | *(Archived)* Legacy Windows bridge setup |

## Quick start (Home-Server Docker)

```bash
cp .env.example .env        # then edit secrets
docker compose up -d        # timescaledb, redis, bot, mt5
curl http://localhost:9090/health
```

## Ports (90xx block, avoids 8xxx)

| Service | Port | Host & Container |
|---------|------|-------------------|
| Bot API / WS | **9090** | Home-Server (`gs-bot`) |
| TimescaleDB | **5433** | Home-Server (`gs-timescaledb`) |
| Redis | **6380** | Home-Server (`gs-redis`) |
| MT5 KasmVNC Web UI | **9096** | Home-Server (`gs-mt5`) |
| MT5 RPyC Bridge | **8001** | Home-Server (`gs-mt5`) |

## Backtesting

```bash
# replay DB history through the full agent stack (synthetic fallback if empty)
docker compose run --rm bot python scripts/smoke_backtest.py
```

The harness swaps only the MT5 client for `backtest.SimBroker`; the orchestrator,
order manager, position manager and risk gate are the exact live ones. Signals
use bars strictly older than the current bar (no look-ahead); entries fill at the
bar open and exits are evaluated against each bar's high/low.

## Status

Phase 0 — Infrastructure & Scaffolding: **complete** (0.1–0.11).
Phase 1 — Agent Framework Core: **complete** (1.1–1.9).
Phase 2 — Market Data & MT5 Connector: **complete** (2.1–2.7) — mock/native/bridge
clients, tick streamer, OHLCV aggregation, session clock, resumable history
downloader.
Phase 3 — Timeframe Division: **complete** (3.1–3.9) — 7 scout agents (M1→D1) +
synthetic DXY factor, HTF vetoes fire end-to-end.
Phase 4 — Risk Division: **complete** (4.1–4.8) — 6 vote-neutral risk agents
(sizing/SL/TP/timing/DD guard/costs) + pre-trade `execution/risk_gate.py`.
Phase 5 — Structure Division: **complete** (5.1–5.6) — 5 agents (market
structure, liquidity, session, microstructure, correlation).
Phase 6 — Technical & Fundamental Divisions: **complete** (6.1–6.10) — 6 tech
agents (Trend/Momentum/Volatility/Volume/SupportResistance/Pattern) + 4 fund
agents (Calendar/NewsSentiment/MacroRegime/Intermarket).
Phase 7 — SPK Core & Infra Divisions: **complete** (7.1–7.5) — 5 vote-neutral
SPK meta-agents (Chief/Aggregator/Resolver/Confidence/Tracker) + 3 infra health
agents. `agents.divisions.build_all_agents` registers the full 37-agent roster.
Phase 8 — Execution: **complete** (8.1–8.5) — MT5 trading primitives on
mock/native/bridge, `execution/order_manager.py`, `execution/position_manager.py`
(breakeven/partial/trailing/time-stop), `core/notifier.py` (Telegram).
Phase 9 — Learning Loop: **complete** (9.1–9.6) — `post_trade_analyzer`
(Lesson Cards), `bandit_optimizer` (Thompson sampling, bounded deltas),
`regime_classifier`, `pattern_library`, wired via `Orchestrator.on_trade_closed`.
Runtime & API: **live** — `runtime.py` wires data→agents→SPK→execution→learning;
FastAPI control/telemetry routes (`/api/status`, `/api/agents`, `/api/patterns`,
`/api/positions`, `/api/control/pause|resume`) behind bearer auth.
Phase 11 — Backtest Harness: **complete** — `backtest/` replays historical OHLCV
through the real orchestrator/order/position managers via a `SimBroker`, with
metrics + `scripts/smoke_backtest.py`.
Phase 10 — API + PWA Frontend: **complete** — REST routes
(`/api/agents|agents/divisions|spk/latest|positions|trades|performance|lessons`,
`/api/control/pause|resume|panic|manual`) + WS telemetry, vanilla-JS PWA
(cockpit, agent grid, division radar, performance, lessons, control).
Phase 12 — MT5 Bridge: **complete (code)** — `bridge/` FastAPI app for the
Windows MT5 host; contract tests in `tests/test_bridge.py`. Live dry-run pending
setup on the Windows host.
215 tests green.

Update history: see [`docs/PROGRESS.md`](docs/PROGRESS.md).

Next: dry-run live terhadap EXNESS demo via bridge.
