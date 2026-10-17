# GoldScalper — Implementation Plan: The Juggler & BizDev Engine

**Version:** 1.0  
**Date:** 2026-10-15  
**Priority:** 🔴 CRITICAL — Root Cause Fix  
**Companions:** [QUANT_FINENG_BIZDEV_SPEC.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/QUANT_FINENG_BIZDEV_SPEC.md) · [PRD.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/PRD.md) · [BLUEPRINT.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/BLUEPRINT.md) · [MULTI_ENTRY_RESCUE_SPEC.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/MULTI_ENTRY_RESCUE_SPEC.md)

---

## Bukti Empiris (Root Cause — Dari Screenshot Live Portfolio)

| Metrik Live | Angka | Diagnosis |
|---|---|---|
| Total PnL | **-$490.38** | Sistem berdarah meski banyak menang |
| Winrate | **64%** (148 menang / 79 kalah) | ✅ Sinyal SPK sudah baik |
| Average Win | **+$5.51** | Normal untuk micro-scalping |
| Average Loss | **-$16.38** | 🔴 **3× lipat kemenangan = akar masalah** |
| Gross Profit | **$883.93** | Bot bisa menghasilkan $800+ sehari |
| Gross Loss | **$1,294.31** | Dimakan bleeding loss tak terkontrol |
| Total Trades | **227 transaksi** | ~13 lot/hari = ~$78–$90 rebate menguap |
| Profit Factor | **0.62** | Target: > 1.5 setelah fix |

**Akar masalah tunggal:** Bot menang 64% waktu, namun membiarkan kekalahan 3× lebih besar dari kemenangan tanpa ada "Juggler" yang menjepit pendarahan dan Circuit Breaker yang mengunci keuntungan.

---

## Aturan Dasar Implementasi

> - **Tidak ada LLM di hot-path.** Seluruh logika Juggler & BizDev adalah kode Python deterministik (<100ms).
> - **Kode dahulu di cabang fitur, uji di mock client, baru deploy live.**
> - **Setiap fase punya Exit Criteria yang terukur** sebelum lanjut ke fase berikutnya.
> - **Settings baru wajib masuk ke `config/settings.py` dan `.env.example`** agar bisa dikonfigurasi tanpa ubah kode.

---

## Fase 1 — THE BLEEDING CLAMP 🩸 (Prioritas Mutlak)

**Goal:** Memotong pendarahan rugi per trade. Dari rata-rata loss -$16.38 → max -$7.00.

**Prinsip:** Max loss per trade tidak boleh melebihi **1.2× average win** (~$6.60). Jika avg win bergeser di masa depan, clamp ikut adaptif.

### 1.1 — Settings Baru: Hard Loss Clamp

**File:** `config/settings.py`

Tambahkan field baru di seksi `# --- Trading / risk ---`:

```python
# --- The Juggler: Hard Loss Clamp (Anti-Bleeding) ---
juggler_enabled: bool = True
hard_loss_clamp_usd: float = 7.00        # Max floating loss per trade sebelum force-cut
hard_loss_clamp_enabled: bool = True
loss_time_decay_seconds: int = 180       # Detik maks posisi minus bisa bertahan
loss_time_decay_min_loss_usd: float = 2.00  # Min loss untuk memicu time-decay cut
```

Ubah nilai default yang sudah ada:

```python
# SEBELUM:
max_hold_seconds: int = 900
max_open_positions: int = 10
stagnant_harvest_seconds: int = 180
stagnant_time_decay_seconds: int = 420
basket_tp_buffer_pips: float = 18.0

# SESUDAH (Small-Capital Sprint Mode):
max_hold_seconds: int = 600             # Turun dari 900 → 600 (10 menit max)
max_open_positions: int = 3             # Turun dari 10 → 3 untuk modal kecil
stagnant_harvest_seconds: int = 120     # Lebih agresif: 2 menit
stagnant_time_decay_seconds: int = 300  # Turun dari 420 → 300
basket_tp_buffer_pips: float = 3.0      # Turun dari 18.0 → 3.0 untuk fast harvest
```

**Exit Criteria:** `python -c "from config.settings import settings; print(settings.hard_loss_clamp_usd)"` → `7.0`

---

### 1.2 — Core Logic: Hard Loss Clamp di `position_manager.py`

**File:** `execution/position_manager.py`

Tambahkan blok Hard Loss Clamp **sebelum** logika stagnant harvest (sekitar baris 83, tepat setelah time-stop):

```python
# Hard Loss Clamp (The Juggler: Anti-Bleeding Mechanism)
# Prevents a single losing trade from exceeding 1.2x the system's average win.
if s.juggler_enabled and s.hard_loss_clamp_enabled:
    current_loss = float(pos.profit or 0.0)
    if current_loss <= -abs(s.hard_loss_clamp_usd):
        log.warning(
            "JUGGLER HARD CLAMP: Force-cutting ticket %s "
            "(loss=%.2f <= -%.2f threshold, side=%s)",
            pos.ticket, current_loss, s.hard_loss_clamp_usd, pos.side,
        )
        await self.client.close_position(pos.ticket, price=price)
        self.untrack(pos.ticket)
        actions.append("juggler_hard_clamp")
        return actions

# Loss Time-Decay Cut (posisi minus dibiarkan > N detik tanpa sinyal balik)
if s.juggler_enabled and state.opened_at is not None:
    current_loss = float(pos.profit or 0.0)
    if (
        held >= s.loss_time_decay_seconds
        and current_loss <= -abs(s.loss_time_decay_min_loss_usd)
    ):
        log.info(
            "JUGGLER TIME-DECAY CUT: Ticket %s held %ds with loss=%.2f",
            pos.ticket, int(held), current_loss,
        )
        await self.client.close_position(pos.ticket, price=price)
        self.untrack(pos.ticket)
        actions.append("juggler_time_decay_cut")
        return actions
```

**Exit Criteria:** Dalam testing mock client, tidak ada posisi yang floating loss > -$7.00 lebih dari 1 detik.

---

## Fase 2 — THE CIRCUIT BREAKER 🔒 (Anti-Giveback)

**Goal:** Mengunci profit begitu target harian 30%–40% tercapai. Bot berhenti total. Tidak ada lagi trade ke-228.

### 2.1 — Settings Baru: Daily Target & Lock

**File:** `config/settings.py`

```python
# --- The Juggler: Daily Target & Circuit Breaker ---
daily_profit_target_pct: float = 35.0    # 35% dari balance awal hari = target harian
daily_profit_lock_enabled: bool = True   # Aktifkan circuit breaker
daily_loss_limit_pct: float = 15.0       # Hard stop rugi harian (override max_daily_loss_pct)
```

Ubah nilai default:
```python
# SEBELUM:
max_daily_loss_pct: float = 3.0   # Terlalu konservatif untuk sprint 30-40%

# SESUDAH:
max_daily_loss_pct: float = 15.0  # Sinkron dengan daily_loss_limit_pct
```

---

### 2.2 — Core Logic: Profit Lock di `DrawdownGuard`

**File:** `agents/divisions/risk/agents.py` (class `DrawdownGuard`)

Tambahkan evaluasi pencapaian target harian di awal method `evaluate()`:

```python
async def evaluate(self, state: SharedState) -> AgentSignal:
    s = self.settings
    reasons: list[str] = []

    # === THE JUGGLER: Daily Profit Lock (Circuit Breaker) ===
    if s.juggler_enabled and s.daily_profit_lock_enabled:
        daily_pnl_pct = state.daily_pnl_pct or 0.0
        if daily_pnl_pct >= s.daily_profit_target_pct:
            reasons.append(
                f"DAILY TARGET ACHIEVED: +{daily_pnl_pct:.1f}% >= "
                f"+{s.daily_profit_target_pct:.1f}% — LOCKED FOR THE DAY!"
            )
            return self.emit(
                " | ".join(reasons),
                {
                    "veto": True,
                    "veto_side": "both",
                    "daily_profit_locked": True,
                    "daily_pnl_pct": round(daily_pnl_pct, 2),
                    "target_pct": s.daily_profit_target_pct,
                    "reasoning": reasons[0],
                },
            )
    # === END CIRCUIT BREAKER ===

    # ... (logika DrawdownGuard yang sudah ada di bawah ini)
```

---

### 2.3 — Enforcement di `order_manager.py`

**File:** `execution/order_manager.py`

Tambahkan pengecekan di awal method `execute()` setelah cek `decision.tradable`:

```python
# === THE JUGGLER: Blokir eksekusi jika daily profit sudah terkunci ===
if getattr(state, 'daily_profit_locked', False):
    log.info(
        "ORDER BLOCKED: Daily profit target achieved — system locked for the day."
    )
    return ExecutionResult(ok=False, reason="daily_profit_locked")
# === END BLOCK ===
```

**Exit Criteria:** Setelah PnL harian menyentuh +35%, tidak ada satu pun order baru yang dieksekusi. Log menampilkan `"daily_profit_locked"`. Notifikasi PWA/Telegram terkirim.

---

## Fase 3 — TARGET-SEEKING LOT SIZER 🎯

**Goal:** Lot tidak lagi statis, tapi adaptif terhadap sisa target harian. Makin dekat target, makin kecil lot (jangan ambisius di garis finish).

### 3.1 — Settings Baru

**File:** `config/settings.py`

```python
# --- The Juggler: Target-Seeking Lot Sizing ---
lot_sizing_mode: str = "TARGET_SEEKING"   # "FIXED" | "ATR_RISK" | "TARGET_SEEKING"
target_seeking_swing_usd: float = 3.00    # Estimasi swing USD per trade (avg swing Gold M1)
```

---

### 3.2 — Logic Baru di `PositionSizer`

**File:** `agents/divisions/risk/agents.py` (class `PositionSizer`)

Tambahkan mode `TARGET_SEEKING` di method `evaluate()`:

```python
# === TARGET-SEEKING MODE (The Juggler) ===
if s.juggler_enabled and s.lot_sizing_mode == "TARGET_SEEKING" and state is not None:
    balance_sod = float(getattr(state, 'balance_start_of_day', equity) or equity)
    target_usd = balance_sod * (s.daily_profit_target_pct / 100.0)
    realized_pnl = float(getattr(state, 'daily_realized_pnl', 0.0) or 0.0)
    remaining_usd = max(0.0, target_usd - realized_pnl)

    if remaining_usd <= 0:
        # Target sudah tercapai, jangan size apapun
        return self.emit("target already reached, sizing zero", {"size": 0.0})

    # Lot = sisa_target / (swing_estimasi × tick_value_per_lot)
    # Tick value Gold: 1 USD move × 1 lot = $100
    swing_per_lot = s.target_seeking_swing_usd * (s.contract_size / 100.0)
    raw_ts = remaining_usd / max(swing_per_lot, 0.01)
    size_ts = min(s.max_lot, max(s.min_lot, round_to_step(raw_ts, s.lot_step)))

    # Safety cap: jangan melebihi 50% dari ATR-risk size
    size = min(size_ts, size * 0.5 + size_ts * 0.5)  # blend ATR & target-seeking
    size = min(s.max_lot, max(s.min_lot, round_to_step(size, s.lot_step)))

    return self.emit(
        f"TARGET_SEEKING: remaining=${remaining_usd:.2f}, lot={size}",
        {
            "size": size,
            "sizing_mode": "TARGET_SEEKING",
            "target_usd": round(target_usd, 2),
            "realized_pnl": round(realized_pnl, 2),
            "remaining_usd": round(remaining_usd, 2),
            "equity": round(equity, 2),
        },
    )
# === END TARGET-SEEKING ===
```

**Exit Criteria:** Saat daily PnL sudah 50% dari target, lot yang diusulkan turun ~50% dibanding lot di awal hari.

---

## Fase 4 — BIZDEV: REBATE & FRICTION TRACKER 💰

**Goal:** Menghitung dan menampilkan arus kas nyata dari volume trading: Rebate IB + Friction Cost.

### 4.1 — Settings Baru

**File:** `config/settings.py`

```python
# --- BizDev: Rebate & Friction Engine ---
bizdev_enabled: bool = True
rebate_per_lot_usd: float = 6.00         # Estimasi rebate IB Exness per lot XAUUSD
max_friction_ratio_pct: float = 15.0     # Batas gesekan biaya: (spread+slip)/gross_profit
```

---

### 4.2 — Tabel DB Baru: `daily_business_metrics`

**File:** `data/timescale/` (migrasi SQL baru)

```sql
-- Migration: daily_business_metrics
CREATE TABLE IF NOT EXISTS daily_business_metrics (
    date            DATE PRIMARY KEY,
    total_lots      NUMERIC(10,2) DEFAULT 0,
    rebate_usd      NUMERIC(10,2) DEFAULT 0,
    gross_profit    NUMERIC(10,2) DEFAULT 0,
    gross_loss      NUMERIC(10,2) DEFAULT 0,
    friction_cost   NUMERIC(10,2) DEFAULT 0,
    friction_ratio  NUMERIC(5,2)  DEFAULT 0,
    net_yield       NUMERIC(10,2) DEFAULT 0,   -- trading_pnl + rebate - friction
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

---

### 4.3 — API Endpoint Baru

**File:** `api/routes/bizdev.py` (file baru)

```python
# GET /api/bizdev/daily
# Returns: { date, total_lots, rebate_usd, friction_ratio, net_yield }
```

---

### 4.4 — Friction Guard di `EntryTiming` Agent

**File:** `agents/divisions/risk/agents.py` (class `EntryTiming`)

Tambahkan pengecekan friction ratio sebelum mengizinkan entry:

```python
# BizDev Friction Guard
if s.bizdev_enabled:
    daily_gross = float(getattr(state, 'daily_gross_profit', 0.0) or 0.0)
    daily_friction = float(getattr(state, 'daily_friction_cost', 0.0) or 0.0)
    if daily_gross > 0:
        friction_ratio = (daily_friction / daily_gross) * 100
        if friction_ratio > s.max_friction_ratio_pct:
            return self.emit(
                f"friction_guard: cost ratio {friction_ratio:.1f}% > {s.max_friction_ratio_pct}%",
                {"spread_ok": False, "friction_blocked": True},
            )
```

**Exit Criteria:** API `/api/bizdev/daily` mengembalikan estimasi rebate yang benar berdasarkan total lot yang terputar hari itu.

---

## Fase 5 — COCKPIT HUD: DAILY PROGRESS CARD 📊

**Goal:** Operator bisa melihat sekilas status target harian, rebate, dan mode bot tanpa membuka tab Portfolio.

### 5.1 — Data yang Perlu Ditambahkan ke WebSocket State

**File:** `api/routes/ws.py` (atau file state broadcaster)

Tambahkan field ke payload telemetri WebSocket:

```json
{
  "juggler": {
    "daily_target_pct": 35.0,
    "daily_pnl_pct": 18.4,
    "progress_pct": 52.6,
    "status": "ACTIVE",
    "daily_realized_pnl_usd": 18.40,
    "remaining_usd": 16.60,
    "profit_locked": false
  },
  "bizdev": {
    "total_lots_today": 8.20,
    "estimated_rebate_usd": 49.20,
    "friction_ratio_pct": 11.3,
    "net_yield_usd": 12.45
  }
}
```

---

### 5.2 — UI Card di Cockpit (Frontend)

**File:** `frontend/js/agents.js` (cockpit render section)

Tambahkan card baru di bawah Symbol Strip di Cockpit View:

```
┌─────────────────────────────────────────────────────┐
│ 🎯 DAILY TARGET          STATUS: ACTIVE             │
│ Progress: ██████████░░░░░░░░░░ 52.6%               │
│ Realized: +$18.40    Remaining: $16.60              │
├───────────────────────┬─────────────────────────────┤
│ 💰 REBATE TODAY       │ ⚡ FRICTION RATIO           │
│  8.20 lot × $6.00     │  11.3% (OK / Batas 15%)    │
│  Est. +$49.20 cashback│  Net Yield: +$12.45         │
└───────────────────────┴─────────────────────────────┘
```

---

## Matriks Dampak yang Diharapkan

| Metrik | Sebelum Fix | Target Setelah Fix |
|---|---|---|
| Avg Loss | **-$16.38** | **≤ -$7.00** (Hard Clamp) |
| Profit Factor | **0.62** | **≥ 1.50** |
| Total PnL Harian | **-$490.38** | **Positif, target +30–40%** |
| Rebate Tercatat | **$0 (tidak dihitung)** | **~$78–$90/hari dari 13 lot** |
| Giveback Risk | **Tinggi (227 trade)** | **Nol (Circuit Breaker aktif)** |

---

## Urutan Eksekusi & Prioritas

```
Fase 1 (KRITIS, Kerjakan Pertama!)
  └── 1.1 → Settings hard_loss_clamp
  └── 1.2 → position_manager.py bleeding clamp
  └── Test mock → Verifikasi tidak ada loss > $7

Fase 2 (KRITIS, Kerjakan Kedua!)
  └── 2.1 → Settings daily_profit_target_pct & lock
  └── 2.2 → DrawdownGuard circuit breaker
  └── 2.3 → order_manager.py block enforcement
  └── Test → Setelah PnL +35%, zero orders pass through

Fase 3 (PENTING, Kerjakan Ketiga)
  └── 3.1 → Settings lot_sizing_mode
  └── 3.2 → PositionSizer TARGET_SEEKING mode
  └── Test → Lot mengecil saat mendekati target

Fase 4 (TAMBAH NILAI, Kerjakan Keempat)
  └── 4.1 → Settings bizdev & rebate
  └── 4.2 → Migrasi DB daily_business_metrics
  └── 4.3 → API /api/bizdev/daily
  └── 4.4 → EntryTiming friction guard

Fase 5 (POLISH, Kerjakan Terakhir)
  └── 5.1 → WebSocket state juggler + bizdev
  └── 5.2 → Cockpit HUD Card
```

---

## Referensi Dokumen Terkait

- [QUANT_FINENG_BIZDEV_SPEC.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/QUANT_FINENG_BIZDEV_SPEC.md) — Arsitektur & konsep lengkap
- [MULTI_ENTRY_RESCUE_SPEC.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/MULTI_ENTRY_RESCUE_SPEC.md) — Spesifikasi basket & rescue
- [PRD.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/PRD.md) — Kebutuhan produk
- [BLUEPRINT.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/BLUEPRINT.md) — Arsitektur sistem Docker
