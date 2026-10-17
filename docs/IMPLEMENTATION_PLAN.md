# GoldScalper — Implementation Plan & Task List

**Version:** 1.0  
**Date:** 2026-10-14  
**Companion:** `PRD.md` · `BLUEPRINT.md`

> **Rules of engagement**
> - Workstation Windows PC is **dedicated 100% to AcengGold**. GoldScalper does not touch or execute on the Windows PC.
> - All GoldScalper services (Core Bot, TimescaleDB, Redis, MT5 Wine Container) run 100% on **Home-Server (`100.114.150.48`)**.
> - Broker account: Exness Demo **#434366152** ($10,000.00 USD, Server: `Exness-MT5Trial7`, Symbol: `XAUUSDm`).
> - Ports: bot **9090**, TimescaleDB **5433**, Redis **6380**, MT5 VNC **9096**, MT5 RPyC **8001** (coexists with 9router:20128).
> - Docs first. Code in phases. Verify each phase before moving on.

---

## Phase 0 — Infrastructure & Scaffolding

**Goal:** Runnable skeleton — containerized DB + Redis + API + tunnel.

| ID | Task | Output | Est. |
|----|------|--------|------|
| 0.1 | Scaffold project tree | All folders per BLUEPRINT §3 | 1h |
| 0.2 | `requirements.txt` + `Dockerfile` | Python 3.11 image | 1h |
| 0.3 | `docker-compose.yml` | timescaledb(5433), redis(6380), bot(9090), cloudflared | 2h |
| 0.4 | `config/settings.py` | pydantic-settings, `.env` loading | 1h |
| 0.5 | `config/logging.py` | structured JSON logs + redaction | 1h |
| 0.6 | `.env.example` | DB_URL, REDIS_URL, MT5 creds, TELEGRAM, API_TOKEN | 1h |
| 0.7 | `data/timescale/001_hypertables.sql` | ticks, ohlcv, agent_decisions, trade_lessons | 2h |
| 0.8 | `data/timescale/002_compression.sql` + `003_retention.sql` | policies | 1h |
| 0.9 | `scripts/init_db.py` | apply migrations on boot | 1h |
| 0.10 | `api/server.py` + `routes/health.py` | FastAPI app, `/health` | 1h |
| 0.11 | Cloudflare Tunnel config | `deploy/cloudflared/config.yml` + DNS route for scalper subdomain | 1h |

**Exit criteria:** `docker compose up -d` → `/health` returns OK at `https://scalper.7pivot.site/health`.

---

## Phase 1 — Agent Framework Core

**Goal:** Framework can register agents, collect weighted votes, produce SPK decision.

| ID | Task | File | Est. |
|----|------|------|------|
| 1.1 | `AgentSignal`, `SPKDecision`, `BaseAgent` | `agents/base.py` | 3h |
| 1.2 | `SharedState` (market cache, positions, consensus) | `agents/state.py` | 2h |
| 1.3 | Redis Streams wrapper (publish/subscribe/consumer groups) | `agents/message_bus.py` | 3h |
| 1.4 | `AgentRegistry` (discovery, weighting, lifecycle) | `agents/registry.py` | 2h |
| 1.5 | SPK voting engine | `spk/voting.py` | 2h |
| 1.6 | SPK veto engine (hard/soft) | `spk/veto.py` | 2h |
| 1.7 | `SPKDecision` model + serialization | `spk/decision.py` | 1h |
| 1.8 | Orchestrator main loop | `agents/orchestrator.py` | 4h |
| 1.9 | Dummy echo agent + unit tests | `tests/test_agents_base.py` | 2h |

**Exit criteria:** Dummy agents run in loop, votes aggregate, decision logged to DB, all unit tests green.

---

## Phase 2 — Market Data & MT5 Connector

**Goal:** Live + historical XAUUSD data flowing into TimescaleDB.

| ID | Task | File | Est. |
|----|------|------|------|
| 2.1 | MT5 connector (connect, reconnect, health) | `core/mt5_connector.py` | 4h |
| 2.2 | Tick stream → Redis `gs:ticks` | `core/mt5_connector.py` | 2h |
| 2.3 | OHLCV aggregation (M1→D1) + cache | `core/market_data.py` | 3h |
| 2.4 | Market session clock (killzones) | `core/clock.py` | 2h |
| 2.5 | Historical downloader (2y, gap-fill, resume) | `scripts/download_history.py` | 4h |
| 2.6 | DB repositories | `data/repositories.py` | 2h |
| 2.7 | Tests: gap-fill, dedupe, aggregation | `tests/test_market_data.py` | 2h |

**Exit criteria:** 2 years of M1→D1 in TimescaleDB, live ticks streaming, no gaps.

---

## Phase 3 — Timeframe Division (7 Agents)

**Goal:** Multi-TF consensus rebuilt as independent agents (reference AcengGold `core/multi_tf_consensus.py` — read only, reimplement).

| ID | Agent | Source Logic | Est. |
|----|-------|--------------|------|
| 3.1 | `TF-M1-Sniper` | M1 trigger | 2h |
| 3.2 | `TF-M5-Inspector` | M5 setup | 2h |
| 3.3 | `TF-M15-Liquidity` | M15 liquidity | 2h |
| 3.4 | `TF-M30-Momentum` | M30 momentum | 2h |
| 3.5 | `TF-H1-Regime` | H1 regime + veto | 2h |
| 3.6 | `TF-H4-Structure` | H4 structure + veto | 2h |
| 3.7 | `TF-D1-Macro` | D1 macro + extreme zone veto | 2h |
| 3.8 | Synthetic DXY factor | correlation | 2h |
| 3.9 | Division tests | `tests/test_timeframe_division.py` | 3h |

**Exit criteria:** 7 TF agents vote independently; H1/H4/D1 vetoes fire correctly.

---

## Phase 4 — Risk Division (6 Agents) [CRITICAL]

**Goal:** Capital protection, fast-harvest scalper economics.

| ID | Agent | Logic | Est. |
|----|-------|-------|------|
| 4.1 | `Risk-PositionSizer` | Vol-adjusted fractional, SPK-weighted | 3h |
| 4.2 | `Risk-StopLoss` | ATR + structure, time stop | 3h |
| 4.3 | `Risk-TakeProfit` | R:R, partial TP, fast harvest | 3h |
| 4.4 | `Risk-EntryTiming` | limit vs market, spread guard | 2h |
| 4.5 | `Risk-DrawdownGuard` | daily/weekly DD, circuit breaker | 2h |
| 4.6 | `Risk-CostMonitor` | spread/slippage/commission tracking | 2h |
| 4.7 | Pre-trade risk gate | `execution/risk_gate.py` | 2h |
| 4.8 | Division tests | `tests/test_risk_division.py` | 3h |

**Exit criteria:** Sizing/SL/TP correct; DD guard halts trading; costs tracked.

---

## Phase 5 — Structure Division (5 Agents)

| ID | Agent | Focus | Est. |
|----|-------|-------|------|
| 5.1 | `Struct-MarketStructure` | BOS, CHoCH, swing HL/LH | 3h |
| 5.2 | `Struct-Liquidity` | OB, FVG, sweeps | 3h |
| 5.3 | `Struct-Session` | killzone, Asia/London/NY | 2h |
| 5.4 | `Struct-Microstructure` | spread, book pressure | 2h |
| 5.5 | `Struct-Correlation` | DXY, yields, silver | 2h |
| 5.6 | Division tests | `tests/test_structure_division.py` | 2h |

---

## Phase 6 — Technical & Fundamental Divisions (10 Agents)

| ID | Agent | Focus | Est. |
|----|-------|-------|------|
| 6.1 | `Tech-Trend` | EMA stack, slope | 2h |
| 6.2 | `Tech-Momentum` | RSI, MACD, stochastic | 2h |
| 6.3 | `Tech-Volatility` | ATR, BB width, regime | 2h |
| 6.4 | `Tech-Volume` | tick volume, delta proxy | 2h |
| 6.5 | `Tech-SupportResistance` | pivots, round numbers | 2h |
| 6.6 | `Tech-Pattern` | engulfing, pin, flags | 2h |
| 6.7 | `Fund-Calendar` | news blackout windows | 2h |
| 6.8 | `Fund-NewsSentiment` | optional async LLM summary | 3h |
| 6.9 | `Fund-MacroRegime` | rates, inflation stance | 2h |
| 6.10 | `Fund-Intermarket` | DXY/equities/bonds | 2h |

---

## Phase 7 — SPK Core Division (5 Agents)

| ID | Agent | Role | Est. |
|----|-------|------|------|
| 7.1 | `SPK-Chief` | final GO/NO-GO, sizing authority | 3h |
| 7.2 | `SPK-Aggregator` | weighted voting per division | 2h |
| 7.3 | `SPK-Resolver` | conflict resolution HTF vs LTF | 3h |
| 7.4 | `SPK-Confidence` | probability + calibration | 2h |
| 7.5 | `SPK-Tracker` | winrate per agent, feeds bandit | 3h |
| 7.6 | SPK integration tests | `tests/test_spk_voting.py`, `tests/test_spk_veto.py` | 4h |

---

## Phase 8 — Execution

| ID | Task | File | Est. |
|----|------|------|------|
| 8.1 | Order manager (submit/modify/cancel) | `execution/order_manager.py` | 4h |
| 8.2 | Position manager (TP/SL/trailing/BE) | `execution/position_manager.py` | 4h |
| 8.3 | Trade recorder → DB | `execution/order_manager.py` | 2h |
| 8.4 | Telegram notifier | `core/notifier.py` | 2h |
| 8.5 | Execution tests (mock MT5) | `tests/test_execution.py` | 3h |

**Exit criteria:** Demo order round-trip works; positions managed; Telegram alerts fire.

---

## Phase 9 — Learning Loop

| ID | Task | File | Est. |
|----|------|------|------|
| 9.1 | Post-trade analyzer → Lesson Cards | `agents/learning/post_trade_analyzer.py` | 4h |
| 9.2 | Bandit optimizer (Thompson Sampling) | `agents/learning/bandit_optimizer.py` | 3h |
| 9.3 | Regime classifier | `agents/learning/regime_classifier.py` | 3h |
| 9.4 | Pattern library rollup | `agents/learning/pattern_library.py` | 2h |
| 9.5 | Wire `on_trade_closed` hook | `agents/orchestrator.py` | 2h |
| 9.6 | Learning tests | `tests/test_learning.py` | 3h |

**Cadence:** online nudge per trade + weekly consolidation (Sunday close).

---

## Phase 10 — API & Frontend (PWA)

| ID | Task | File | Est. |
|----|------|------|------|
| 10.1 | WS manager + telemetry push | `api/ws_manager.py`, `api/routes/telemetry.py` | 3h |
| 10.2 | Agents/divisions routes | `api/routes/agents.py` | 2h |
| 10.3 | Trades/lessons/performance routes | `api/routes/{trades,lessons,performance}.py` | 3h |
| 10.4 | Control routes (pause/panic/manual) | `api/routes/control.py` | 2h |
| 10.5 | Cockpit view (chart + positions) | `frontend/js/app.js` | 4h |
| 10.6 | Agent grid view | `frontend/js/agents.js`, `css/agents.css` | 4h |
| 10.7 | Division radar + SPK trace | `frontend/js/agents.js` | 4h |
| 10.8 | Performance + lessons views | `frontend/js/agents.js` | 4h |
| 10.9 | PWA manifest + service worker | `manifest.json`, `sw.js` | 2h |
| 10.10 | API tests | `tests/test_api.py` | 3h |

**Design standard:** dark neutrals, single accent, lucide icons (no emoji/ASCII),
custom toast/modal/select, `min-h-[100dvh]`, custom scrollbar, 4-state handling.

---

## Phase 11 — Historical Data & Backtest

| ID | Task | File | Est. |
|----|------|------|------|
| 11.1 | Full history download (2y all TF) | `scripts/download_history.py` | (in P2) |
| 11.2 | Event-driven replay engine | `scripts/backtest_replay.py` | 4h |
| 11.3 | Agent accuracy validation | `scripts/validate_agents.py` | 2h |
| 11.4 | KPI report generator | `scripts/backtest_replay.py` | 2h |

---

## Phase 12 — Deployment & Soak

| ID | Task | Est. |
|----|------|------|
| 12.1 | Cloudflare Access policy (email OTP) | 1h |
| 12.2 | Backup strategy for TimescaleDB | 2h |
| 12.3 | Telegram alert integration E2E | 1h |
| 12.4 | 1-week demo soak test | — |
| 12.5 | Runbook (start/stop/recover) | 2h |

---

## Mobile Access Decision (Answered)

**Recommended: Cloudflare Tunnel + Cloudflare Access** for `scalper.7pivot.site`.
- Works on any Android browser, HTTPS, no port forwarding
- Cloudflare Access adds email-OTP gate
- PWA "Add to Home Screen" → app-like experience
- Optional: Tailscale as private admin fallback

---

## Port Map (Final)

| Service | Port |
|---------|------|
| Bot API / WS | **9090** |
| TimescaleDB | **5433** |
| Redis | **6380** |
| Nginx (internal) | **9080** |

---

## Milestone Summary

| Milestone | Phases | Outcome |
|-----------|--------|---------|
| **M1: Skeleton** | 0, 1 | Containerized framework + dummy agents + SPK |
| **M2: Data** | 2, 3 | Live + 2y history, 7 TF agents |
| **M3: Protection** | 4, 5, 6 | Risk + Structure + Technical/Fundamental |
| **M4: Brain** | 7, 8 | SPK Core + execution on demo |
| **M5: Learning** | 9 | Lesson cards + adaptive weights |
| **M6: UX** | 10 | PWA dashboard (desktop + mobile) |
| **M7: Validation** | 11, 12 | Backtest + soak + deploy |

---

## Immediate Next Step

Start **Phase 0.1–0.6**: scaffold tree, requirements, Dockerfile, docker-compose,
settings, logging, `.env.example`. Then Phase 0.7–0.11 (DB schema + tunnel).

> Awaiting go-ahead to write code. Docs delivered as requested.