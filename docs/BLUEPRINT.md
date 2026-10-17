# GoldScalper — Technical Blueprint

**Version:** 1.0  
**Date:** 2026-10-14  
**Companion:** `PRD.md` (requirements) · `QUANT_FINENG_BIZDEV_SPEC.md` (quant & bizdev) · `MULTI_ENTRY_RESCUE_SPEC.md` (rescue engine) · `IMPLEMENTATION_PLAN.md` (tasks) · `IMPLEMENTATION_PLAN_JUGGLER_BIZDEV.md` (juggler & bizdev fix) · `IMPLEMENTATION_PLAN_INSTITUTIONAL_SMC.md` (institutional SMC & session clocks)

---

## 1. System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│             GoldScalper Architecture (100% Home-Server Docker)           │
│                                                                          │
│   [gs-mt5 (Wine/RPyC)]  (Home-Server Docker container :9096/:8001)       │
│            │  ticks / orders (Internal gs-net bridge)                    │
│            ▼                                                             │
│   ┌──────────────────┐        ┌─────────────────────────────────────┐   │
│   │  MT5 Connector   │◄──────►│         ORCHESTRATOR LOOP           │   │
│   │  (Data Gateway)  │        │  collect → SPK → execute → learn    │   │
│   └────────┬─────────┘        └───────┬─────────────┬───────────────┘   │
│            │                          │             │                    │
│            ▼                          ▼             ▼                    │
│   ┌────────────────┐          ┌──────────────┐ ┌──────────────────┐    │
│   │  Redis Streams │◄────────►│  Agent Pool  │ │  Learning Loop   │    │
│   │  (message bus) │          │  7 divisions │ │  bandit + cards  │    │
│   └────────┬───────┘          │  37 agents   │ └────────┬─────────┘    │
│            │                  └──────────────┘          │               │
│            ▼                                            ▼               │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                     TimescaleDB (PostgreSQL)                     │  │
│   │  ticks · ohlcv · agent_decisions · trades · lessons · weights   │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│            ▲                                                            │
│            │  REST + WebSocket                                          │
│   ┌────────┴─────────┐                                                  │
│   │   FastAPI Server │  port 9090 (gs-bot, custom non-8xxx)            │
│   └────────┬─────────┘                                                  │
│            ▼                                                            │
│   ┌──────────────────┐     Cloudflare Tunnel      ┌─────────────────┐  │
│   │  PWA Frontend    │◄──────────────────────────►│ scalper.        │  │
│   │  (desktop/mobile)│                            │ 7pivot.site     │  │
│   └──────────────────┘                            └─────────────────┘  │
│                                                                          │
│   * Workstation Windows PC: 100% Bebas untuk Project AcengGold          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Port Allocation (Avoid 8xxxx & Multi-App Coexistence)

| Service | Port | Host & Container | Notes |
|---------|------|-------------------|-------|
| FastAPI (bot API + WS) | **9090** | Home-Server (`gs-bot`) | Main app port |
| TimescaleDB | **5433** | Home-Server (`gs-timescaledb`) | 5432 used elsewhere |
| Redis | **6380** | Home-Server (`gs-redis`) | 6379 used elsewhere |
| MetaTrader 5 KasmVNC | **9096** | Home-Server (`gs-mt5`) | Web browser MT5 terminal GUI |
| MT5 RPyC Bridge | **8001** | Home-Server (`gs-mt5`) | Internal RPC connection to Wine MT5 |
| 9router (existing) | 20128 | Home-Server | Untouched |
| Headroom (existing) | 8787 | Home-Server | Untouched |
| AcengGold (existing) | 8080/818x | **Windows PC** | Dedicated on Windows workstation |

> Convention: GoldScalper uses **90xx** block on Home-Server. Avoids 8xxx and coexists with all existing apps without touching the Windows PC.

---

## 3. Directory Structure

```
GoldScalper/
├── docs/
│   ├── PRD.md
│   ├── BLUEPRINT.md
│   └── IMPLEMENTATION_PLAN.md
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── .env                            # gitignored, real secrets
├── requirements.txt
├── run.py                          # entrypoint / orchestrator bootstrap
├── README.md
│
├── config/
│   ├── __init__.py
│   ├── settings.py                 # pydantic-settings
│   └── logging.py
│
├── core/
│   ├── __init__.py
│   ├── mt5_connector.py            # async MT5 data + execution
│   ├── market_data.py              # OHLCV cache, TF aggregation
│   ├── clock.py                    # market session clock
│   ├── calendar_service.py         # real-time economic calendar & news blackout guard
│   ├── cross_asset.py              # MT5 FX majors ticker & synthetic DXY momentum
│   ├── news_sentiment_service.py   # financial RSS headline scraper & Fed macro bias
│   └── notifier.py                 # Telegram alert dispatcher
│
├── agents/
│   ├── __init__.py
│   ├── base.py                     # BaseAgent, AgentSignal, SPKDecision
│   ├── registry.py                 # discovery, weighting, lifecycle
│   ├── message_bus.py              # Redis Streams wrapper
│   ├── state.py                    # SharedState
│   ├── orchestrator.py             # main decision loop
│   ├── divisions/
│   │   ├── timeframe/              # 7 agents
│   │   ├── technical/              # 6 agents
│   │   ├── structure/              # 5 agents
│   │   ├── risk/                   # 6 agents
│   │   ├── fundamental/            # 4 agents
│   │   ├── spk/                    # 5 agents
│   │   └── infra/                  # 3 agents
│   └── learning/
│       ├── bandit_optimizer.py
│       ├── regime_classifier.py
│       └── post_trade_analyzer.py
│
├── spk/
│   ├── __init__.py
│   ├── voting.py                   # weighted vote aggregation
│   ├── veto.py                     # hard/soft veto rules
│   └── decision.py                 # SPKDecision model + serialization
│
├── execution/
│   ├── __init__.py
│   ├── order_manager.py            # order lifecycle
│   ├── position_manager.py         # TP/SL/trailing
│   └── risk_gate.py                # pre-trade hard checks
│
├── data/
│   ├── __init__.py
│   ├── db.py                       # asyncpg / SQLAlchemy engine
│   ├── models.py                   # ORM models
│   ├── repositories.py             # data access layer
│   └── timescale/
│       ├── 001_hypertables.sql
│       ├── 002_compression.sql
│       └── 003_retention.sql
│
├── api/
│   ├── __init__.py
│   ├── server.py                   # FastAPI app factory
│   ├── ws_manager.py               # WebSocket connection manager
│   └── routes/
│       ├── health.py
│       ├── telemetry.py
│       ├── agents.py
│       ├── trades.py
│       ├── lessons.py
│       └── control.py              # panic/pause/manual
│
├── frontend/
│   ├── index.html
│   ├── manifest.json
│   ├── sw.js
│   ├── css/
│   │   ├── cockpit.css
│   │   └── agents.css
│   └── js/
│       ├── app.js
│       ├── ws.js
│       ├── components.js
│       └── agents.js
│
├── scripts/
│   ├── init_db.py
│   ├── download_history.py
│   ├── backtest_replay.py
│   └── validate_agents.py
│
├── tests/
│   ├── test_agents_base.py
│   ├── test_spk_voting.py
│   ├── test_spk_veto.py
│   ├── test_risk_division.py
│   ├── test_timeframe_division.py
│   ├── test_orchestrator.py
│   ├── test_learning.py
│   └── test_api.py
│
└── deploy/
    ├── cloudflared/
    │   └── config.yml
    └── nginx/
        └── scalper.conf
```

---

## 4. Agent Contract (Core Interface)

```python
# agents/base.py (design spec)

@dataclass
class AgentSignal:
    agent_id: str
    division: str
    timeframe: str | None
    vote: int              # -1 SELL | 0 NEUTRAL | +1 BUY
    confidence: float      # 0.0 – 1.0
    weight: float          # 0.0 – 5.0 (tuned by bandit)
    veto: str | None       # None | "VETO_BUY" | "VETO_SELL"
    reasoning: str         # human-readable
    metadata: dict         # indicators, levels, etc.
    ts: datetime
    latency_ms: float

@dataclass
class SPKDecision:
    action: str            # BUY | SELL | HOLD
    score: float           # weighted consensus score
    confidence: float
    size: float            # lots
    sl: float
    tp: float
    hard_veto: bool
    veto_reason: str | None
    votes: list[AgentSignal]
    ts: datetime

class BaseAgent(ABC):
    id: str
    division: str
    default_weight: float

    @abstractmethod
    async def evaluate(self, state: SharedState) -> AgentSignal: ...

    async def run_cycle(self, state, bus): ...   # loop + publish + ack
```

---

## 5. SPK Voting Model

### 5.1 Score Computation

```
score = Σ (vote_i × confidence_i × weight_i)
```

### 5.2 Default Division Weights

| Division | Weight | Rationale |
|----------|--------|-----------|
| Risk | 2.0 | Capital protection is paramount |
| SPK Core | 1.5 | Decision brain |
| Timeframe HTF (H1,H4,D1) | 1.5 | Veto power, macro bias |
| Structure | 1.3 | Liquidity & session edge |
| Timeframe LTF (M1,M5,M15,M30) | 1.2 | Entry precision |
| Technical | 1.0 | Confirmation |
| Fundamental | 0.8 | News filter |
| Infra | 0.5 | Health only (no vote) |

### 5.3 Decision Thresholds

| Score Range | Action |
|-------------|--------|
| ≥ +2.0 | STRONG BUY |
| +0.5 … +2.0 | BUY |
| -0.5 … +0.5 | HOLD (chop) |
| -2.0 … -0.5 | SELL |
| ≤ -2.0 | STRONG SELL |
| any hard veto | BLOCK |

### 5.4 Veto & Boundary Protection Rules

**Hard Veto & Hard Barrier (block entirely):**
- **Hard Barrier Protection (Anti-Pucuk):** S/R rejection or BSL/SSL sweep with $\ge 0.70$ confidence from `Tech-SupportResistance`, `Struct-Liquidity`, or `Tech-Pattern` **CANNOT be softened or overridden** by momentum scores. Blocks BUY at Resistance and SELL at Support.
- **Reversal Confluence Trigger:** When a hard barrier blocks an entry, the system inspects M1 fast rejection (`TF-M1-Sniper`, `Tech-Pattern`). If confirmed without opposite vetoes, the system immediately flips to a counter-trend reversal (e.g., BUY blocked at Resistance flips to SELL) with tight SL (+$1.80) and TP (-$6.00, 1:4 RRR).
- **Post-Trade & Post-Basket Cooldown:** 60s cooldown on trade close and 120s cooldown on basket TP prevents immediate re-entry at exhausted price points.
- **S/R Boundary Guard on Rescue Layers:** Blocks buying rescue layers into a resistance breakdown or selling into support bounce.
- H1 vote opposes trade direction
- D1 Extreme Zone (premium/discount > 90%)
- H4 Supply/Demand block touch against direction
- News blackout (HIGH impact ±30 min)
- Daily loss limit / DD guard triggered

**Soft Veto (reduce confidence):**
- HTF conflict (H1 vs LTF) → −30% confidence
- Spread > MAX_SPREAD_PIPS → −20%
- Low-liquidity session → −15%

> **Response to user question:** SPK does **not** require realtime LLM inference.
> It is fully deterministic (rule + weighted voting), sub-100ms. AI/LLM is used
> only in the **async learning loop** (post-trade analysis, regime tagging,
> weight optimization), never in the hot path.

---

## 6. Data Model (TimescaleDB)

### 6.1 Hypertables

```sql
-- ticks (raw, short retention)
ticks(time TIMESTAMPTZ, symbol TEXT, bid DOUBLE, ask DOUBLE, volume DOUBLE)
  → hypertable(time, chunk 1 day), retention 7 days

-- ohlcv (aggregated, long retention)
ohlcv(time TIMESTAMPTZ, symbol TEXT, timeframe TEXT,
      open, high, low, close DOUBLE, volume DOUBLE,
      spread_avg DOUBLE)
  → hypertable(time, chunk 7 days), retention 5 years, compress after 30d

-- agent_decisions
agent_decisions(time TIMESTAMPTZ, trade_id UUID, agent_id TEXT,
                division TEXT, vote INT, confidence DOUBLE, weight DOUBLE,
                veto TEXT, reasoning TEXT, latency_ms DOUBLE, metadata JSONB)
  → hypertable(time, chunk 1 day), retention 1 year

-- trade_lessons
trade_lessons(time TIMESTAMPTZ, trade_id UUID, regime TEXT,
              outcome TEXT, root_cause TEXT, action TEXT,
              score DOUBLE, tags TEXT[])
  → hypertable(time, chunk 30 days)
```

### 6.2 Regular Tables

```sql
trades(id UUID PK, opened_at, closed_at, symbol, direction, size,
       entry, sl, tp, exit, pnl, pips, duration_s,
       spk_score, spk_confidence, regime, session, status)

agent_weights(agent_id TEXT PK, weight DOUBLE, updated_at,
              trades_seen INT, wins INT, losses INT, winrate DOUBLE)

regimes(id, name, detected_at, features JSONB)
```

---

## 7. Message Bus (Redis Streams)

| Stream | Producer | Consumer(s) | Purpose |
|--------|----------|-------------|---------|
| `gs:ticks` | MT5 Connector | Data agents | Live price feed |
| `gs:signals` | All agents | Aggregator | Agent votes |
| `gs:spk` | Aggregator | Chief, Execution | Consensus decisions |
| `gs:execution` | Chief | Order Manager | Order intents |
| `gs:filled` | Order Manager | Learning, Tracker | Fill events |
| `gs:events` | All | API WS bridge | Push to frontend |

Consumer groups per division for horizontal scaling.

---

## 8. Orchestrator Loop (Pseudocode)

```python
async def run_forever():
    await registry.bootstrap()
    await mt5.connect()

    while running:
        state = await build_shared_state()      # refresh market data

        # 1. Parallel agent evaluation
        signals = await asyncio.gather(
            *[agent.run_cycle(state, bus) for agent in registry.active()]
        )

        # 2. SPK aggregation
        decision = spk.evaluate(signals)

        # 3. Hard veto gate
        if decision.hard_veto:
            await bus.publish("gs:spk", decision)
            continue

        # 4. Pre-trade risk gate
        if not risk_gate.allow(decision, state):
            continue

        # 5. Execute
        order = await order_manager.submit(decision)

        # 6. Broadcast to UI
        await ws.broadcast(decision)
        await bus.publish("gs:events", decision)

        await asyncio.sleep(cycle_interval)   # e.g. 1s on M1

# Post-trade hook (fired on close)
async def on_trade_closed(trade):
    await post_trade_analyzer.analyze(trade)          # lesson card
    await bandit_optimizer.update(trade, agent_votes)  # weight tuning
    await regime_classifier.tag(trade)                 # regime label
```

### 8.1 Multi-Entry & Defensive Rescue Architecture

GoldScalper mendukung eksekusi multi-posisi secara otomatis (hingga `max_open_positions = 10`) dengan evaluasi konsensus seluruh 37 agen (8 divisi):

1. **Dual Multi-Entry Paradigm:**
   - **Trend Scaling / Pyramiding:** Menambah posisi searah tren ketika posisi awal telah floating profit (+R) dan konfirmasi HTF berlanjut.
   - **Defensive Rescue Mode (Smart Reversal Recovery):** Ketika posisi awal floating minus akibat koreksi/liquidity sweep, sistem **tidak melakukan martingale buta**, melainkan mengevaluasi konfluensi titik pembalikan (*Structure S/R + OrderFlow Absorption + Technical Oversold/Overbought + Risk Sizing*).
2. **Basket Position Management:**
   - Menghitung **Average Break-Even Price** dinamis dari seluruh posisi aktif.
   - Menggeser Take-Profit keranjang (*Basket TP*) ke beberapa pips di atas titik impas gabungan untuk menutup seluruh paket posisi dengan net profit aman saat harga pullback.
   - Dilindungi oleh sirkuit pemutus darurat `DrawdownGuard`.

> Spesifikasi teknis lengkap, formula matematis break-even, dan integrasi antar divisi terdokumentasi di [`docs/MULTI_ENTRY_RESCUE_SPEC.md`](./MULTI_ENTRY_RESCUE_SPEC.md).

### 8.2 Trend vs Sideways Arbitration & Anti-Hedging S/R Barrier

Untuk mencegah jebakan posisi berlawanan (*ping-pong cross-hedged pincer*) di mana bot membeli di puncak resistensi dan menjual di lantai support saat sideways, sistem menerapkan arsitektur proteksi 3 lapis:

1. **Dewan Hakim Trend vs Sideways (3-Judge Arbitration):**
   - **Hakim 1 (`Struct-MarketStructure`):** Mengidentifikasi fraktal swing high/low M5 & M15 (`HH_HL` = Uptrend, `LH_LL` = Downtrend, `RANGE` = Sideways).
   - **Hakim 2 (`TF-H1-Regime` & `TF-M15`):** Menentukan arah makro 24 jam dan slope EMA21. Jika M15 berbeda arah dari H1, status regime diklasifikasikan sebagai `CONTESTED / SIDEWAYS`.
   - **Hakim 3 (`Tech-SupportResistance`):** Mengukur lebar kanal harga (*Channel Span*). Jika selisih batas atas dan bawah $\le \$10.00$, pasar dinyatakan dalam kompresi konsolidasi (*sideways range*). Dilengkapi filter anti-outlier spike 2nd-order extreme agar wick berita tunggal tidak mendistorsi level support/resistance struktural.
   
2. **Anti-Hedging S/R Barrier Guard (`order_manager.py`):**
   - Ketika posisi berlawanan telah ada (*hedged state*), dilarang membuka posisi SELL berlawanan di area lantai support ($Support \pm \$1.50$) dan dilarang membuka posisi BUY berlawanan di area atap resistensi ($Resistance \pm \$1.50$).
   - **Trend Continuation Breakout Exemption:** Formula blokir ini **TIDAK** mematikan breakout tren sejati. Eksekusi searah breakout diizinkan jika dan hanya jika terdapat konfirmasi penutupan body candle M5 bersih menembus batas ($Close_{M5} < Support - 0.50$ untuk breakdown, atau $Close_{M5} > Resistance + 0.50$ untuk breakout) dengan dukungan struktur fraktal yang valid.

3. **Cross-Hedged Basket Recovery & Time Salvage Exit (`position_manager.py`):**
   - Jika keranjang posisi mengandung posisi BUY dan SELL sekaligus, target keluar tidak menggunakan rerata harga satu arah, melainkan **Net Aggregate PnL**:
     $$\text{Net PnL} = \sum \text{PnL}_{\text{BUY}} + \sum \text{PnL}_{\text{SELL}} \ge +\$1.50$$
   - **Stagnant Time-Decay Salvage:** Jika posisi terjebak $\ge 120$ detik, threshold diturunkan ke $\ge +\$0.50$ untuk segera melepaskan modal (*fast unlock*) begitu menyentuh profit tipis.

---

## 9. Learning Loop

| Component | Method | Trigger |
|-----------|--------|---------|
| **Weight Optimizer** | Thompson Sampling per agent | Every closed trade (online) + weekly batch |
| **Regime Classifier** | Feature clustering (vol, trend, session) | Every closed trade |
| **Post-Trade Analyzer** | Rule templates + optional LLM summary | Every closed trade |
| **Pattern Library** | Setup signature → winrate stats | Rollup hourly |

**Update cadence (fast scalper):**
- Online weight nudge: after each trade
- Weekly consolidation: Sunday market close
- Human approval for changes > 20% weight delta

---

## 10. Frontend (PWA)

| View | Data Source | Key Components |
|------|-------------|----------------|
| **Cockpit** (default) | WS telemetry | Price chart (lightweight-charts), positions, P&L, SPK score |
| **Agents** | `/api/agents` + WS | Agent grid, status dots, latency bars, weight sliders |
| **Divisions** | `/api/agents/divisions` | Consensus radar, veto flags, heatmap |
| **SPK Trace** | `/api/spk/latest` | Decision tree, vote breakdown, veto reasons |
| **Performance** | `/api/performance` | Winrate matrix, weight evolution chart, equity curve |
| **Lessons** | `/api/lessons` | Filterable lesson cards, tag cloud |
| **Control** | `/api/control/*` | Pause, Panic Close, Manual BUY/SELL, config |

Design standards: dark neutral theme, single accent, no emoji/ASCII icons,
lucide icons, custom select/toast/modal, `min-h-[100dvh]`, custom scrollbar.

---

## 11. Deployment Topology

```
                        Internet
                           │
                    Cloudflare (DNS + Tunnel + Access)
                           │  scalper.7pivot.site
                           ▼
        ┌──────────────────────────────────────────┐
        │           HOME SERVER (Docker)            │
        │                                           │
        │  cloudflared ──► nginx(9080) ──► bot(9090)│
        │                     │                     │
        │                timescaledb(5433)          │
        │                redis(6380)                │
        │                                           │
        │  9router (20128)  ← existing, untouched   │
        └───────────────────┬───────────────────────┘
                            │ LAN / host.docker.internal
                            ▼
        ┌──────────────────────────────────────────┐
        │     WINDOWS MT5 HOST (this PC)            │
        │  MetaTrader 5 Terminal (EXNESS demo)      │
        │  gs-mt5-bridge (orders + quotes)          │
        └──────────────────────────────────────────┘
```

### 11.1 Mobile Access Recommendation (Answer to Q3)

Three options when away from home:

| Option | Setup | Pros | Cons |
|--------|-------|------|------|
| **A. Cloudflare Tunnel (RECOMMENDED)** | Already used by 9router | Free, HTTPS, Access auth, no port forward | Needs tunnel config |
| **B. Tailscale VPN** | Install on server + phone | Zero-trust, private, no public exposure | Requires app on phone |
| **C. Port forward + DDNS** | Router config | Direct | Security risk, ISP blocks |

**Recommendation: A (Cloudflare Tunnel) + Cloudflare Access (email OTP)** for
`scalper.7pivot.site`. This mirrors the existing 9router setup, gives HTTPS +
auth on any Android browser, and PWA "Add to Home Screen" makes it app-like.
Optionally add **B (Tailscale)** as a private fallback admin path.

> **Architecture Update:** GoldScalper runs 100% self-contained on the Home-Server
> inside Docker containers, including MT5 (Wine headless + RPyC bridge `:8001` & KasmVNC `:9096`).
> The Windows Workstation PC is completely free and 100% dedicated to the `AcengGold` project.

---

## 12. Security & Multi-User Architecture

- **Multi-User Authentication**: Email + Password login via bcrypt (`rounds=12`), issuing HMAC-SHA256 JWT bearer tokens (30 days validity).
- **Multi-Tenant MT5 Accounts**: Users link their own personal Exness account (login, trading password, server, lot size, active state) stored securely in TimescaleDB `user_trading_accounts`.
- **Master Operator Fallback**: System master token (`API_TOKEN`) preserved for headless automation, CLI, and internal health checks.
- **WebSocket Auth**: Guarded by JWT/token validation before accepting connection.
- **Rate limiting**: Enforced on control and execution endpoints (panic/pause/manual).
- **Audit trail**: Every order, SPK consensus vote, and configuration change recorded with user correlation ID.
- **Zero secrets in logs**: Credentials redacted by JSON logger filters.

---

## 13. Observability

| Signal | Tool | Retention |
|--------|------|-----------|
| Structured logs | JSON to stdout → Docker log driver | 30 days |
| Metrics | Prometheus endpoint `/metrics` | 90 days |
| Traces | OpenTelemetry spans per cycle | 7 days |
| Dashboards | Grafana (optional Phase 2) | — |
| Alerts | Telegram bot | — |

---

## 14. Testing Strategy

| Layer | Method | Coverage Target |
|-------|--------|-----------------|
| Unit (agents) | pytest, mock SharedState | 80% |
| Unit (SPK) | Deterministic vote scenarios | 90% |
| Integration | Redis + DB in Docker, mock MT5 | 70% |
| Backtest | Historical replay, KPI report | — |
| Load | 36 agents × 1s cycle | p99 < 100ms |
| E2E | Demo account, 1 week soak | — |

---

## 15. Technology Stack Summary

| Layer | Choice |
|-------|--------|
| Language | Python 3.11+ |
| Async | asyncio + httpx |
| API | FastAPI + uvicorn |
| Messaging | Redis Streams |
| Time-series DB | TimescaleDB (PostgreSQL 16) |
| ORM | SQLAlchemy 2.0 (async) + asyncpg |
| MT5 | MetaTrader5 Python package |
| Frontend | Vanilla JS + lightweight-charts + lucide |
| Container | Docker + docker-compose |
| Tunnel | cloudflared |
| Notifications | Telegram Bot API |
| Testing | pytest + pytest-asyncio |
| Lint | ruff |
| Types | mypy |