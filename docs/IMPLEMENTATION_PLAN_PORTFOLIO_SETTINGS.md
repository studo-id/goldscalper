# Implementation Plan: Portfolio & Settings Architecture Upgrade

**Status:** Proposed / Awaiting Approval  
**Date:** 2026-10-15  
**Project:** GoldScalper (XAUUSD Multi-Agent Cockpit)  
**Directive:** Strict Borderless UI Architecture (`AGENTS.md`)  

---

## 1. Executive Summary & Objectives

This implementation plan refactors the GoldScalper frontend navigation and view architecture:
1. **Consolidate `Performance` & `Lessons` into `Portfolio`:**
   - Move the Post-Trade Retrospective engine from the standalone `Lessons` page directly into `Portfolio` as an **Expandable Master-Detail Trade Ledger** placed under the 3 statistical cards.
   - Bind the Trade Ledger to the existing **Filter Periode** (Hari Ini, Kemarin, 7 Hari, 30 Hari, Semua, Kustom).
   - Retire the standalone `Lessons` view from the navigation.
2. **Refactor `Control` into a Multi-Tab `Settings` Hub:**
   - Organize operations, risk configurations, and system telemetry into 3 clean, borderless tabs:
     - **Tab 1: Operations & Emergency** (Runtime loop, Panic close all, Manual order modal, Active floating positions monitor with individual ticket close).
     - **Tab 2: Risk & Scalping Parameters** (Risk % per trade, Max daily loss %, Max open positions, Max spread barrier, R:R & ATR multipliers, Max hold time).
     - **Tab 3: System & Connectivity** (MT5 broker bridge status, TimescaleDB & Redis health, Telegram alert status, 37-agent cycle loop telemetry).
3. **Streamline Sidebar Navigation:**
   - Reduce sidebar items from 6 to 5: `Cockpit` → `Agents` → `Divisions` → `Portfolio` → `Settings`.
4. **Preserve 100% Borderless Architecture:**
   - Zero outer container borders, pure tonal dark elevation surfaces (`#0b0e14`, `#11151c`, `#161b24`, `#1c2330`), tabular `JetBrains Mono` figures, and status-only left indicators.

---

## 2. Navigation & Architecture Transformation

```
[ CURRENT ARCHITECTURE (6 Views) ]
├── Cockpit
├── Agents
├── Divisions
├── Performance (Filter + KPIs + Equity Chart + 3 Cards)
├── Lessons     (Card list of retrospectives) ──────────┐ [Merged into Portfolio]
└── Control     (Runtime + Killswitch + Trade Table) ───┼─► Moved to Portfolio
                                                        └─► Refactored to Settings (3 Tabs)

[ NEW ARCHITECTURE (5 Views) ]
├── Cockpit       (Live trading cockpit)
├── Agents        (37 sub-agent telemetry)
├── Divisions     (Division clusters & correlation)
├── Portfolio     (Filter + KPIs + Equity Chart + 3 Cards + Unified Trade & Retrospective Ledger)
└── Settings      (3 Tabs: Operations, Risk Parameters, System Connectivity)
```

---

## 3. Detailed View Specifications

### A. View: `Portfolio` (formerly `Performance`)

The layout follows a natural macro-to-micro analytical funnel:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Filter Periode: [Hari Ini] [Kemarin] [7 Hari] [30 Hari] [Semua] [Kustom]│
├────────────────────────────────────────────────────────────────────────┤
│ [TOTAL PNL]  [WIN RATE]  [PROFIT FACTOR]  [TRADES]  [EQUITY]  [MAX DD] │
├────────────────────────────────────────────────────────────────────────┤
│ EQUITY GROWTH CURVE (Sumbu Y di Kiri, Sumbu X di Bawah)                │
│ ┌────────────────────────────────────────────────────────────────────┐ │
│ │$10k ┼────\                                                         │ │
│ │$9.8k┼─────\─────────/\───────/\─────────────────────────────────── │ │
│ │$9.6k┼──────\───────/  \─────/  \───────\                           │ │
│ │$9.4k┼───────\_____/    \___/    \_______\__________/\__________o   │ │
│ │     ┴──────────────┬──────────────┬──────────────┬──────────────┬─ │ │
│ │   14 Oct 22:30   15 Oct 02:15   15 Oct 05:30   15 Oct 12:00   Now  │ │
│ └────────────────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────────────────┤
│ [OUTCOME BREAKDOWN]      [TRADE AVERAGES]       [GROSS RETURNS]        │
├────────────────────────────────────────────────────────────────────────┤
│ ▼ UNIFIED TRADE & RETROSPECTIVE LEDGER (Filtered by Period)            │
│ ┌────────────────────────────────────────────────────────────────────┐ │
│ │ TICKET     SIDE  LOT   ENTRY    EXIT     PNL     DUR   ROOT CAUSE  │ │
│ ├────────────────────────────────────────────────────────────────────┤ │
│ │ 4879427635 BUY   0.10  4,155.5  4,155.9  +$3.74  236s  confirmed ▼ │ │
│ │  └─► ACCORDION DETAIL:                                             │ │
│ │       • Adaptive Policy: keep weight; reinforce setup              │ │
│ │       • Agent Score: 1.00 · Weight Adj: 0.00                       │ │
│ │       • Closed: 15 Oct 17:15 (2m ago)                              │ │
│ ├────────────────────────────────────────────────────────────────────┤ │
│ │ 4879410451 SELL  0.09  4,156.5  4,156.8  -$2.64  2s    premature ▼ │ │
│ │  └─► ACCORDION DETAIL:                                             │ │
│ │       • Adaptive Policy: review entry timing; avoid reversal stops │ │
│ │       • Agent Score: -1.00 · Weight Adj: -0.05                     │ │
│ │       • Closed: 15 Oct 17:08 (9m ago)                              │ │
│ └────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

#### Key Technical Features of Portfolio:
- **Correlated Data:** When the user clicks a filter pill (e.g. `7 Hari`), the backend `/api/performance` endpoint is called. The trade list is synced with `p.trades` or `/api/lessons` to render only trades falling within that window.
- **Accordion Toggle:** Clicking any row smoothly expands a borderless dark panel (`var(--s2)` surface) detailing the agent's cognitive reflection without leaving the page.
- **Pagination / Infinite Scroll:** Includes a subtle borderless "Load More Trades" button if the dataset exceeds the initial batch.

---

### B. View: `Settings` (formerly `Control`)

Features a top segmented pill switcher to toggle between 3 dedicated operational scopes:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Settings                                                               │
│ [ Operations & Emergency ]   [ Risk & Parameters ]   [ System Status ] │
├────────────────────────────────────────────────────────────────────────┤
```

#### Tab 1: `Operations & Emergency`
- **Runtime Loop:** Switch between `Running` and `Paused` (stops new agent entries while preserving active position SL/TP management).
- **Emergency Killswitch:** `Panic Close All` button with real-time open trade counter badge.
- **Manual Order Modal:** Button to launch modal order dialog (Buy/Sell, Lot size, SL/TP).
- **Active Floating Positions Table (NEW):**
  - Displays currently open/floating orders (`Ticket`, `Side`, `Lots`, `Open Price`, `Current Price`, `Floating PnL`, `SL`, `TP`).
  - Includes a direct `Close` button per open position via `/api/control/close?ticket=...`.

#### Tab 2: `Risk & Scalping Parameters`
- Readout and interactive parameter inspection from `config/settings.py` and `RuntimeDep`:
  - **Account Capital Risk:** `Risk per Trade: 0.5%` · `Max Daily Loss: 3.0%` · `Max Weekly Loss: 6.0%`.
  - **Trade Barriers:** `Max Spread: 45 pts` · `Max Consecutive Losses: 4` · `Max Open Positions: 10`.
  - **Harvest Multipliers:** `Default R:R: 1.5` · `ATR SL Multiplier: 1.2` · `Max Hold: 900s (15m)`.
  - Note badge explaining: *"Dynamic runtime safeguards monitored every 1,000ms loop"*.

#### Tab 3: `System & Connectivity`
- Real-time health cards:
  - **MetaTrader 5 Bridge:** Server connection (`Exness-Real10`), Login, Magic Number (`990001`), Algo Trading Allowed status (`True`).
  - **Database & Message Bus:** TimescaleDB connection pool (`10/20`), Redis host & port (`6380`).
  - **Telegram Alerts:** Notification module status (`Active` / `Disabled`).
  - **Agent Decision Stream:** 37 Agents cycle latency and WebSocket pump heartbeat.

---

## 4. Phase-by-Phase Execution Plan

### Phase 1: Data Model & Integration
- Verify endpoints:
  - `/api/performance` (serves KPI metrics, equity curve points, and outcome distributions).
  - `/api/trades` & `/api/lessons` (serves closed trades and retrospective analysis).
  - `/api/status` & `/api/telemetry` (serves open positions and runtime configuration).
  - Ensure `/api/performance` can supply both trade execution metrics and lesson metadata, or join `/api/lessons` seamlessly in frontend state.

### Phase 2: Refactor `Performance` into `Portfolio`
- **File:** `frontend/js/agents.js`
  - Rename `performance` view object to `portfolio` (or alias it).
  - Update `title: "Portfolio"`, `sub: "realized metrics & post-trade ledger"`, `icon: "trending"`.
  - Append the `Unified Trade & Retrospective Ledger` underneath the 3 statistical cards.
  - Implement row click accordion state toggling (`expandedTicketId`).
  - Connect the ledger to the active date filter so changing filters updates the table.
- **File:** `frontend/css/agents.css`
  - Style the ledger table, badge chips, and expandable detail accordion with pure borderless dark tokens (`--bg`, `--s1`, `--s2`, `--s3`).

### Phase 3: Refactor `Control` into `Settings` with 3 Tabs
- **File:** `frontend/js/agents.js`
  - Rename `control` view object to `settings`.
  - Update `title: "Settings"`, `sub: "operations, risk & system configuration"`, `icon: "sliders"`.
  - Implement internal tab state: `activeTab: "ops" | "risk" | "system"`.
  - Render Tab 1 (`Operations & Emergency` + Active Floating Positions table).
  - Render Tab 2 (`Risk & Scalping Parameters` grid).
  - Render Tab 3 (`System & Connectivity` status cards).
- **File:** `frontend/css/agents.css`
  - Add tab styles and parameter grid cards matching the borderless aesthetic.

### Phase 4: Update Router, Nav & Deprecate `Lessons`
- **File:** `frontend/js/app.js`
  - Update `ORDER` array from:
    `["cockpit", "agents", "divisions", "performance", "lessons", "control"]`
    to:
    `["cockpit", "agents", "divisions", "portfolio", "settings"]`
  - Update icon mapping for `portfolio` and `settings`.
  - Add route fallbacks for backward compatibility (`#performance` → `portfolio`, `#control` → `settings`).
- **File:** `frontend/index.html`
  - Bump cache buster query string to `v=20261015_11`.

### Phase 5: Testing & Production Deployment
- **Syntax Check:** Run `node --check` across modified JavaScript files.
- **Strict Borderless UI Audit:** Verify no rogue borders or container outlines are introduced (`AGENTS.md` directive).
- **Deploy to Remote Server (`100.114.150.48`):**
  - Transfer `agents.js`, `app.js`, `agents.css`, and `index.html` to `/home/studo/apps/goldscalper/frontend/`.
  - Verify live HTTP status via `curl`.
  - Verify container and UI in browser.
