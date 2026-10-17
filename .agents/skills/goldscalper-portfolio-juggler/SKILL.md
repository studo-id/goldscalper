---
name: goldscalper-portfolio-juggler
description: Enforces that all trading strategy recommendations, risk gating, position sizing, SL/TP dynamics, and multi-entry layering in GoldScalper strictly anchor to real-time daily portfolio performance and sprint target proximity.
---

# GoldScalper Portfolio-First & Daily Target Juggler Skill

## Core Philosophy: The Juggler Engine
Trading is not evaluated candle-by-candle in a vacuum. Every setup, order, sizing decision, and exit must be dynamically calibrated against:
1. **Daily Portfolio Health (`daily_pnl_pct`, `daily_realized_pnl`)**
2. **Sprint Target Proximity (`remaining_target_usd`, `daily_profit_target_pct`)**
3. **Live Win Statistics (`live_avg_win`, `winrate`)**

Static, hardcoded parameters that ignore portfolio health are STRICTLY FORBIDDEN.

---

## The 3 Operating Modes

### 1. DEFENSE Mode (`daily_pnl_pct < 0%`)
- **Objective:** Capital Preservation & Bleeding Prevention.
- **Sizing:** Sizer applies `health_mult = max(0.65, 1.0 + pnl_pct / 50.0)`, keeping lots strictly at 0.02–0.04.
- **SPK Consensus:** Threshold is penalized up to `+60%` (`weak_threshold *= (1.0 + min(0.60, abs(pnl_pct)/15.0))`), silencing single-agent noise and requiring strong multi-division confluence.
- **Vetoes:** Soft vetoes (HTF conflict, wide spread, low liquidity) are amplified by up to `1.5x`.
- **Pyramiding:** BANNED.
- **Multi-Entry Layering:** Minimum separation expanded to $\ge 30-35$ pips ($3.00–$3.50). If drawdown $\le -4.0\%$, layering is completely disabled.

### 2. GROWTH Mode (`daily_pnl_pct >= +3%`)
- **Objective:** Compounding & Momentum Riding using Market Gains (*house money*).
- **Sizing:** Sizer applies `health_mult = min(1.40, 1.0 + pnl_pct / 100.0)`, permitting expansion up to 0.06–0.10 lot.
- **SPK Consensus:** Strong threshold softens by 8% (`strong_threshold *= 0.92`) to quickly catch high-momentum waves.
- **Pyramiding:** Allowed ONLY if existing positions are ALREADY IN PROFIT ($+\$1.50$ / 15 pips).
- **Bleeding Clamp:** Dynamically expands using market profit cushion: `max(7.0, live_avg_win * 1.1) * health_mult`.

### 3. BALANCED Mode (`0% <= daily_pnl_pct < 3%`)
- **Objective:** High-conviction entry with disciplined baseline limits.
- **Sizing:** `health_mult = 1.0`. Baseline sizing from ATR and standard clamp.

---

## Finish Line Lockdown (`remaining_target_usd <= $20`)
- **Finish Line Rule:** When within $20 of the daily profit target:
  - Multi-entry layering and pyramiding are **DISABLED** (Strict single-position mode).
  - SPK entry bar is tightened (`weak_threshold * 1.10 - 1.35`) so marginal trades do not risk the day's profits.
  - Wide spread tolerance is reduced (caution triggered at $> 75\%$ of max spread).
- **Target Achieved (`daily_profit_locked == True` or `remaining_target <= 0`):**
  - SPK returns `(ACTION_HOLD, STRENGTH_NONE)` immediately.
  - Hard veto blocks any new market orders.

---

## Payoff & Exit Heuristics
- **Early Break-Even Lock:** Automatically slides SL to `entry + 0.15` when floating profit reaches $+25$ pips ($+\$2.50$), securing a risk-free $+0.60$ win.
- **Runner Harvesting:** Position breathes until reaching $\ge \$7.50$ (or $1.25\times \text{avg win}$) unless HTF scouts actively oppose the trend.
- **HTF Breakdown Cut:** If floating loss reaches $65\%$ of clamp budget AND HTF scouts (H4/H1/M30/M15) actively oppose the trade, cut immediately. Never hope for a reversal against higher-timeframe order flow.
