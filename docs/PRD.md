# GoldScalper — Product Requirements Document (PRD)

**Version:** 1.0  
**Date:** 2026-10-14  
**Status:** Draft for Implementation  
**Project Folder:** `C:\Users\STUDO\Documents\Project\APPS\trading\GoldScalper`  
**Reference System:** AcengGold (read-only, production) at `C:\Users\STUDO\Documents\Project\APPS\trading\AcengGold`  
**Companions:** `BLUEPRINT.md` (architecture) · `QUANT_FINENG_BIZDEV_SPEC.md` (quant & bizdev) · `MULTI_ENTRY_RESCUE_SPEC.md` (rescue engine) · `IMPLEMENTATION_PLAN_INSTITUTIONAL_SMC.md` (institutional SMC & session clocks)

---

## 1. Executive Summary

Build a **multi-agent AI scalping system for XAUUSD (Gold)** on **M1 timeframe** as an agile companion to `AcengGold` with:
- **High-Yield Small-Capital Sprint** — dirancang khusus untuk modal kecil ($50–$200+) dengan target pertumbuhan agresif **30% – 40% per hari**
- **Automated "Done-for-the-Day" Circuit Breaker** — mengunci total profit harian begitu menyentuh target 30%–40% guna mencegah overtrading & kelelahan mental
- **The Juggler (Financial Engineer)** — dynamic target-seeking lot sizing dan in-flight multi-position break-even pullback
- **BizDev Rebate Engine** — ekstraksi arus kas rebate IB ($3–$8/lot) dari frekuensi perdagangan tinggi sebagai booster modal
- **Fast entry, fast exit** — micro-scalping dengan take profit fokus
- **SPK (Sistem Pengambilan Keputusan)** by agent consensus
- **7 Divisions × 37 Agents** — specialized analysis per division (Timeframe, Risk, Structure, Technical, Fundamental, SPK Core, Infra)
- **Active Fundamental Division Feeds** — real-time Economic Calendar, News Sentiment analysis, Macro Regime tracker, and Cross-Asset correlations (DXY & Silver delta)
- **Learning loop** — "beli data" via demo account, learn from every loss/win via Thompson Sampling bandit & automated Lesson Cards
- **Desktop (2-Column Optimized) + Mobile (PWA)** — user-friendly dashboard with side-by-side Division Consensus & Spider/Radar chart
- **Live EXNESS MT5 execution** — demo/live account `#434366152` (Server: `Exness-Real10` / `Exness-MT5Trial7`, Symbol: `XAUUSDm`) with live equity & balance bridge integration
- **100% Self-hosted on Home-Server (`100.114.150.48`)** — subdomain `scalper.7pivot.site` via Cloudflare Tunnel, MT5 fully containerized via Wine & internal bridge
- **Zero footprint on Windows PC** — Workstation Windows PC dialokasikan khusus 100% untuk sistem utama `AcengGold`

---

## 2. Problem Statement

| Current Pain | GoldScalper Solution |
|--------------|---------------------|
| Single-strategy bot, no multi-timeframe context | 7-TF agent division (M1→D1) with veto power |
| Manual parameter tuning | Agent weights auto-adjusted via bandit optimizer |
| No post-trade learning | Post-Trade Analyzer agent generates "Lesson Cards" |
| Passive/dormant fundamental analysis | Real-time external news, calendar blackout windows & cross-asset sentiment pipelines |
| Static/dummy account balance display | Real-time bidirectional MT5 bridge synchronizing actual balance, equity, and floating PnL |
| Wasted vertical screen space on desktop | Modern 2-column responsive layout with side-by-side Division list and Spider Radar |
| Desktop-only monitoring | PWA + mobile-responsive dashboard |
| Tied to single workstation PC | 100% Home-server Docker deployment, Cloudflare Tunnel access |
| No historical replay | Event-driven backtest with agent decision replay |

---

## 3. User Personas

| Persona | Needs | Priority |
|---------|-------|----------|
| **Solo Trader (You)** | Fast scalping, risk control, mobile monitoring, learn from data | P0 |
| **Agent Developer (You)** | Modular agent framework, clear interfaces, observability | P0 |
| **Future Scale** | Multi-symbol, multi-account, live capital | P2 |

---

## 4. Functional Requirements

### 4.1 Core Trading Engine

| ID | Requirement | Detail |
|----|-------------|--------|
| FR-01 | **M1 Scalping Execution** | Entry → TP/SL within seconds-minutes, max hold configurable |
| FR-02 | **Multi-Timeframe Consensus** | 7 agents (M1, M5, M15, M30, H1, H4, D1) vote with veto |
| FR-03 | **SPK Decision Engine** | Weighted voting, hard/soft veto, confidence scoring, conflict resolution |
| FR-04 | **Risk Division** | 6 agents: Position Sizing, SL, TP, Entry Timing, DD Guard, Cost Monitor |
| FR-05 | **Structure Division** | 5 agents: Market Structure, Liquidity, Session, Microstructure, Correlation |
| FR-06 | **Technical Division** | 6 agents: Trend, Momentum, Volatility, Volume, S/R, Pattern |
| FR-07 | **Fundamental Division** | 4 agents: Calendar (blackout window), News Sentiment (finviz/forexlive RSS), Macro Regime (Fed hawkish/dovish bias), Intermarket (DXY/Silver cross-asset deltas) |
| FR-08 | **SPK Core Division** | 5 agents: Chief, Aggregator, Resolver, Confidence, Tracker |
| FR-09 | **Infra Division** | 3 agents: Heartbeat, Connectivity, Resource Monitor |

### 4.2 Learning & Adaptation

| ID | Requirement | Detail |
|----|-------------|--------|
| FR-10 | **Post-Trade Analysis** | Auto-generate Lesson Card per trade (win/loss) |
| FR-11 | **Agent Weight Optimization** | Thompson Sampling bandit — online per trade + batch weekly |
| FR-12 | **Regime Classification** | Tag each trade with market regime (trending/sideways/news/vol) |
| FR-13 | **Pattern Library** | Store recurring setup patterns with winrate stats |

### 4.3 Data & Infrastructure

| ID | Requirement | Detail |
|----|-------------|--------|
| FR-14 | **TimescaleDB** | Hypertable for ticks, OHLCV, agent decisions, trades, lessons |
| FR-15 | **Redis Streams** | Inter-agent messaging, pub/sub, consumer groups |
| FR-16 | **MT5 Connector** | Async tick streaming, order execution, position management via containerized Wine bridge |
| FR-17 | **Historical Downloader** | Pull 2 years M1→D1 from MT5 demo, gap-fill, deduplicate |
| FR-18 | **Event-Driven Backtest** | Replay with full agent decision logging |

### 4.4 Dashboard (PWA)

| ID | Requirement | Detail |
|----|-------------|--------|
| FR-19 | **Real-time Telemetry** | WebSocket: live Bid/Ask, real-time equity & balance from Exness MT5 bridge, positions, agent votes, SPK decision, risk metrics |
| FR-20 | **Agent Monitor** | Grid: status, latency, last vote, confidence, weight per agent |
| FR-21 | **Division Radar (2-Column Desktop)** | Desktop view 2-kolom berdampingan: Division Consensus di kiri dan Spider/Radar Chart di kanan untuk efisiensi ruang pandang tanpa scroll vertikal |
| FR-22 | **SPK Trace** | Decision tree visualization (Chief → Aggregator → Resolution) |
| FR-23 | **Performance Matrix** | Winrate, P&L, weight evolution per agent/division |
| FR-24 | **Lesson Feed** | Filterable lesson cards from post-trade analysis |
| FR-25 | **Mobile PWA** | Add to Home Screen, offline queue, push notifications |
| FR-26 | **Manual Override** | Panic Close, Pause Bot, Manual Order (BUY/SELL) |
| FR-27 | **Multi-User Auth Portal** | Email & Password authentication with bcrypt & JWT tokens (No OTP) |
| FR-28 | **Personal Exness MT5 Account** | Multi-tenant account mapping in TimescaleDB with custom lot size & active status |
| FR-29 | **Multi-Entry & Smart Rescue Mode** | Up to 10 open positions with 37-agent confluence; defensive rescue layering with dynamic basket break-even exit |
| FR-30 | **Real-time Account Bridge Sync** | Full bidirectional MT5 sync for accurate equity, balance, margin, and live floating PnL (eliminating dummy fallback values) |
| FR-31 | **Hard Barrier & Boundary Protection** | S/R rejection & BSL/SSL sweeps (>= 0.70 conf) act as non-softenable hard vetoes, preventing buying at the top/selling at bottom |
| FR-32 | **Reversal Confluence Trigger** | When a hard barrier blocks entry, M1 price action rejection triggers an instant counter-trend reversal (1:4 RRR) with tight SL |
| FR-33 | **Post-Trade & Post-Basket Cooldown** | Mandatory cooldown timer (60s trade, 120s basket) preventing instant re-entry at exhausted price levels |
| FR-34 | **Trend vs Sideways Arbitration & Anti-Hedging S/R Barrier** | 3-Judge consensus (MarketStructure, H1/M15, Tech S/R) decides regime; blocks opposite hedging at S/R floor/ceiling unless confirmed breakdown/breakout |

---

## 5. Non-Functional Requirements

| Category | Requirement | Target |
|----------|-------------|--------|
| **Latency** | Agent evaluation cycle | < 100ms per cycle |
| **Latency** | Order execution (MT5) | < 500ms roundtrip |
| **Availability** | Bot uptime (demo) | 99% during market hours |
| **Scalability** | Agents per division | 10+ (horizontal via Redis Streams) |
| **Security** | API auth | Bearer token / JWT + Cloudflare Access |
| **Security** | MT5 credentials | Encrypted in .env, never in code |
| **Observability** | Logging | Structured JSON, correlation IDs |
| **Observability** | Metrics | Prometheus / Grafana ready |
| **Mobile** | PWA installability | Lighthouse PWA score > 90 |
| **Mobile** | Offline capability | Queue manual orders, sync on reconnect |

---

## 6. Constraints & Assumptions

| Constraint | Detail |
|------------|--------|
| **Solo development** | All code by one person — modular, maintainable |
| **AcengGold read-only** | No modifications to production system |
| **Demo account only** | EXNESS demo, "beli data" mindset |
| **Home-server 100%** | All services including MT5 run inside Docker on Home-Server (`100.114.150.48`) |
| **Workstation PC Free** | Zero footprint on Windows PC — workstation dialokasikan 100% untuk AcengGold |
| **No LLM in hot path** | SPK = deterministic rules only; AI for learning loop only |
| **Self-hosted infra** | TimescaleDB, Redis, Nginx, Bot, MT5-Wine in Docker |

---

## 7. Success Metrics (KPIs)

| Metric | Target (Pilot 3 Months) |
|--------|------------------------|
| **Trade Frequency** | 50-200 trades/day (M1 scalper) |
| **Win Rate** | > 55% (after learning phase) |
| **Profit Factor** | > 1.3 |
| **Max Drawdown** | < 5% daily, < 10% weekly |
| **Agent Decision Latency** | P99 < 100ms |
| **System Uptime** | > 99% market hours |
| **Lesson Cards Generated** | 100% of closed trades |
| **Weight Convergence** | Stable weights after 500 trades |

---

## 8. Out of Scope (Phase 1)

- Live capital deployment (prop-firm or real cash)
- Multi-symbol trading (XAGUSD, BTC, etc. — currently used only for synthetic correlation analysis)
- Advanced heavy deep learning models (transformers, RL) in 1s decision hot path
- App Store / Play Store native app compilation (pure PWA focus)
- Broker abstraction beyond MetaTrader 5 (EXNESS MT5 focus)

---

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| MT5 connection instability | High | High | Reconnection logic, mock fallback, health monitor agent |
| Overfitting agent weights | Medium | High | Bandit exploration rate, minimum trade threshold |
| Data gaps in historical | Medium | Medium | Gap-fill validation, alert on missing bars |
| Cloudflare Tunnel downtime | Low | Medium | Local LAN fallback, Tailscale VPN option |
| SPK veto too aggressive | Medium | Medium | Tunable veto thresholds, audit log review |

---

## 10. Glossary

| Term | Definition |
|------|------------|
| **SPK** | Sistem Pengambilan Keputusan — Decision Making System |
| **Agent** | Autonomous analysis unit with vote, confidence, reasoning |
| **Division** | Group of agents with shared domain (Timeframe, Risk, etc.) |
| **Veto** | Hard block (veto_buy/veto_sell) or soft (confidence reduction) |
| **Lesson Card** | Auto-generated post-trade analysis with root cause & action |
| **Bandit Optimizer** | Thompson Sampling for adaptive agent weight adjustment |
| **Hypertable** | TimescaleDB partitioned time-series table |
| **PWA** | Progressive Web App — installable, offline-capable web app |