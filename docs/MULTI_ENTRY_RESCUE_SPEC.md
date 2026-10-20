# GoldScalper — Multi-Entry & Defensive Rescue Mode Specification

**Version:** 1.0  
**Date:** 2026-10-14  
**Status:** Approved Architecture Blueprint  
**Target:** XAUUSD (Gold) M1 Micro-Scalping Engine  
**Companions:** [PRD.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/PRD.md) · [BLUEPRINT.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/BLUEPRINT.md) · [QUANT_FINENG_BIZDEV_SPEC.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/QUANT_FINENG_BIZDEV_SPEC.md)  

---

## 1. Overview & Objectives

GoldScalper dirancang bukan sebagai bot grid/martingale buta yang menumpuk posisi tanpa dasar, melainkan sistem scalping institusional berbasis **37 Agen (8 Divisi)**. Dokumen ini mendefinisikan arsitektur **Multi-Entry Execution** dan **Defensive Rescue Mode (Smart Recovery)** untuk memaksimalkan peluang profit saat tren kuat, sekaligus mengamankan modal dan memulihkan posisi ketika pasar berbalik arah (*market reversal/whipsaw*).

### Key Objectives:
1. **Target-Aware Multi-Entry (Max 2 Positions for Small-Capital Sprint):** Membatasi bot membuka hingga maksimal 2 posisi terbuka per sisi (1 initial + 1 rescue layer) secara presisi dengan jarak minimum $\ge 20$ pips agar tidak membebani margin akun kecil ($50–$200), dengan batas absolut akun besar maksimal 10 posisi.
2. **Defensive Rescue Mode (Smart Recovery):** Ketika posisi mengalami *floating drawdown* akibat koreksi mendadak, bot mendeteksi zona pembalikan (*reversal pivot*) dan mengeksekusi posisi penyelamatan terukur.
3. **Basket Take-Profit & Break-Even Pullback:** Seluruh posisi dalam keranjang (*basket*) dikelola secara kolektif dengan dynamic average break-even point + fast harvest buffer (3 pips).
4. **Hard Capital Preservation & Daily Target Lock:** Menjaga eksposur margin agar tetap di atas 300% dan menghentikan trading begitu target harian 30%–40% tercapai via `DrawdownGuard`.

---

## 2. Multi-Entry Modes

```
                                  ┌──────────────────────────────┐
                                  │   SPK Evaluation (37 Agents) │
                                  └──────────────┬───────────────┘
                                                 │
                                                 ▼
                                     ┌───────────────────────┐
                                     │ Ada Open Position(s)? │
                                     └─────┬───────────┬─────┘
                                           │           │
                                       TIDAK          YA
                                           │           │
                     ┌─────────────────────┘           ▼
                     ▼                     ┌─────────────────────────────┐
        ┌─────────────────────────┐        │ Status Floating PnL Basket? │
        │ Initial Fresh Entry     │        └──────┬───────────────┬──────┘
        │ Standard SPK Confluence │               │               │
        └─────────────────────────┘          PROFIT (+)       LOSS (-)
                                                  │               │
                                                  ▼               ▼
                                    ┌──────────────────┐ ┌──────────────────┐
                                    │ Mode A: Pyramiding│ │ Mode B: Rescue   │
                                    │ Trend Scaling-In │ │ Smart Recovery   │
                                    └──────────────────┘ └──────────────────┘
```

### 2.1 Mode A: Trend Pyramiding (Scaling-In)
- **Kondisi:** Posisi awal wajib sudah dalam kondisi **Floating Profit (≥ +1.5 USD / 15 pips)**.
- **Syarat Mutlak Juggler:**
  - **DILARANG KERAS Pyramiding saat Portfolio Drawdown (`daily_pnl_pct < 0%`).** Pyramiding hanya diizinkan saat portfolio netral atau profit (`GROWTH` mode).
  - Dilarang pyramiding jika floating posisi sebelumnya masih minus atau flat ($\le 0$).
- **Trigger:** Divisi Timeframe (M5/M15/H1) dan Structure mengonfirmasi kelanjutan tren (*trend continuation*).
- **Eksekusi:** Menambah posisi kedua dengan lot yang disesuaikan, sambil menggeser Stop Loss posisi pertama ke Break-Even (+Lock Profit).

### 2.2 Mode B: Defensive Rescue Mode (Smart Reversal Recovery)
- **Kondisi:** Posisi awal mengalami **Floating Loss** akibat *liquidity sweep*, false breakout, atau koreksi tajam.
- **Prinsip Utama:** **DILARANG** melakukan averaging buta (bukan martingale tanpa batas). Entry penyelamatan **hanya dipicu jika 8 divisi mendeteksi titik konfluensi pembalikan arah baru**.
- **Jarak Minimum Juggler (Spreading Heuristic):**
  - **Normal / Growth Mode:** Minimum jarak antar layer adalah **$\ge 20$ pips ($2.00 USD)**.
  - **Defense Mode (`daily_pnl_pct < 0%`):** Minimum jarak antar layer diperlebar ke **$\ge 30–35$ pips ($3.00–$3.50 USD)** untuk mencegah *clustering* berdekatan saat pasar trending tajam melawan posisi.
- **Finish Line Lockdown:**
  - Ketika sisa target harian tinggal sedikit (**`remaining_target_usd \le $20`**), atau drawdown mendalam (**`daily_pnl_pct \le -4.0%`**), sistem otomatis mengunci mode **Single Position Only** (seluruh multi-entry dan rescue layering diblokir total untuk mengamankan modal/target).
- **Maksimal Rescue Layers:** Maksimal 2 layer penyelamatan per sisi (dengan batas absolut `max_open_positions = 10`).

### 2.3 Anti-Hedging S/R Barrier & Anti-Pucuk/Dasar Trap
- **Prinsip:** DILARANG membuka posisi hedging berlawanan arah (*Ping-Pong*) di area batas ekstrim:
  - **Dilarang SELL Lawan di Support Floor ($4144 \pm 1.5\text{ USD}$):** Mencegah terjebak menjual di lantai saat harga sedang memantul.
  - **Dilarang BUY Lawan di Resistance Ceiling ($4154 \pm 1.5\text{ USD}$):** Mencegah terjebak membeli di atap saat harga sedang tertolak.
- **Pengecualian Breakout Sejati:** Proteksi ini hanya memperbolehkan eksekusi jika terjadi **Confirmed Structural Breakdown/Breakout** (Candle M5 resmi *Close* di luar level batas didukung struktur `LH_LL` atau `HH_HL`).

### 2.4 Dewan Hakim Pemutus Kondisi Pasar (Trend vs Sideways)
Penentuan rezim pasar diatur secara desentralisasi oleh 3 Hakim Utama:
1. **Hakim 1 (`Struct-MarketStructure`):** Fraktal swing `HH_HL` (Uptrend), `LH_LL` (Downtrend), atau `RANGE` (Sideways).
2. **Hakim 2 (`TF-H1-Regime` & `TF-M15`):** Kemiringan slope EMA21 H1 dan keselarasan multi-timeframe. Jika M15 BUY dan H1 SELL saling berlawanan $\rightarrow$ **CONTESTED / SIDEWAYS**.
3. **Hakim 3 (`Tech-SupportResistance`):** Mengukur bentang range horizontal menggunakan **Cluster Body S/R** (kebal terhadap ekor jarum outlier berita). Range $\le \$10.00\text{ USD} \rightarrow$ **SIDEWAYS**.

---

## 3. Peran & Kontribusi 8 Divisi dalam Rescue Mode

Setiap entri penyelamatan (*rescue entry*) wajib diverifikasi oleh sinyal lintas divisi:

| Divisi | Agen Kunci | Peran dalam Mode Penyelamatan |
|---|---|---|
| **Structure** | `Structure-MarketStructure`<br>`Structure-Liquidity`<br>`Structure-Microstructure` | Mendeteksi apakah pergerakan berlawanan adalah *Liquidity Sweep / Stop Hunt* di area penting (Order Block, Fair Value Gap / S/R). Memvalidasi Reversal Pivot. |
| **OrderFlow & Volume** | `Technical-Volume`<br>`Structure-Microstructure` | Memvalidasi *Volume Absorption* dan *Exhaustion* (tekanan seller/buyer mulai habis di level diskon/premium). |
| **Technical** | `Technical-Momentum`<br>`Technical-Volatility`<br>`Technical-SupportResistance` | Konfirmasi osilator ekstrim (RSI Oversold/Overbought, Bullish/Bearish Divergence, Bollinger Band rejection). |
| **Timeframe** | `Timeframe-H1`<br>`Timeframe-M15`<br>`Timeframe-M5`<br>`Timeframe-M1` | Memastikan struktur Higher Timeframe (H1/H4) masih mendukung arah skenario besar dan tidak mengalami *regime shift* total. |
| **Fundamental & Macro** | `Fundamental-Calendar`<br>`Fundamental-MacroRegime` | Menjamin tidak ada *High Impact News Blackout* (misal rilis CPI/NFP/FOMC) yang dapat memicu slippage tak terkendali. |
| **Risk Division** | `Risk-PositionSizer`<br>`Risk-DrawdownGuard`<br>`Risk-CostMonitor` | Menghitung lot penyelamatan proporsional (sizing fractional terkalibrasi), memverifikasi margin level > 300%, dan memastikan spread broker tetap normal. |
| **SPK Core** | `SPK-Chief`<br>`SPK-Aggregator`<br>`SPK-Resolver` | Menghitung bobot skor konfluensi. Memberikan otorisasi final jika sinyal pembalikan mencapai ambang konsensus. |

---

## 4. Mekanisme Basket Position Manager & Dynamic Exit

Ketika terdapat lebih dari 1 posisi terbuka (multi-position basket), `PositionManager` mengaktifkan logika **Basket Trailing & Exit**:

### 4.1 Average Break-Even Calculation
Formula titik impas gabungan:
$$\text{Price}_{\text{BE}} = \frac{\sum (\text{Entry}_i \times \text{Volume}_i)}{\sum \text{Volume}_i}$$

### 4.2 Dynamic Basket Take-Profit (Basket TP)
- Daripada menunggu posisi awal kembali ke target profit semula (yang mungkin membutuhkan jarak tempuh harga yang jauh), target Take-Profit untuk **SELURUH** posisi dalam keranjang disesuaikan ke:
$$\text{Target TP}_{\text{Basket}} = \text{Price}_{\text{BE}} + (\text{Buffer Pips})$$
*(Buffer Pips standar: 5–15 pips di atas titik impas gabungan untuk menutupi komisi broker dan mengunci net profit bersih).*
- Begitu harga memantul (*rebound*) sedikit saja melewati $\text{Price}_{\text{BE}}$, `PositionManager` mengeksekusi **Close All Basket Positions** secara serentak.

### 4.3 Emergency Rescue Circuit Breaker (Hard Veto)
Jika harga terus menembus zona invalidasi struktural terakhir dan kerugian total basket mendekati batas `max_daily_loss_pct` (3.0%):
- `DrawdownGuard` memicu **Hard Veto**.
- Seluruh posisi dalam keranjang langsung ditutup (*emergency flatten*) untuk membatasi kerugian modal.

### 4.4 Cross-Hedged Basket Recovery & Stagnant Time-Decay Salvage
- **Cross-Hedge Net Exit:** Ketika keranjang berisi posisi dua arah (BUY dan SELL aktif bersamaan), titik target tidak menggunakan `avg_entry` melainkan **Net Aggregate PnL**:
  $$\text{Net PnL} = \sum \text{Profit}_i \ge \text{Min Buffer} \ (\ge +\$1.50)$$
  Begitu PnL gabungan berbalik positif, seluruh posisi ditutup serentak untuk membuka kuncian hedge.
- **Stagnant Trade Time Salvage (Scalper Ethos):**
  - **3 Menit (180s):** Jika posisi tertahan $\ge 3$ menit dan profit $\ge +\$2.50 \rightarrow$ langsung panen cepat (*stagnant harvest*).
  - **7 Menit (420s):** Jika posisi tertahan $\ge 7$ menit dan profit $\ge +\$0.50$ (walau tipis) $\rightarrow$ langsung tutup (*time-decay salvage*) demi menyelamatkan modal.
  - **15 Menit (900s):** Batas waktu maksimal (*hard time-stop*).

---

## 5. Konfigurasi Parameter (Settings & Environment)

Parameter yang dikonfigurasi di `config/settings.py` dan `.env`:

```env
# Multi-Entry & Rescue Parameters
MAX_OPEN_POSITIONS=10              # Batas kuota maksimal open posisi bersamaan
MULTI_ENTRY_ENABLED=true          # Mengaktifkan kapabilitas multi-entry bot
RESCUE_MODE_ENABLED=true           # Mengaktifkan mode penyelamatan cerdas
RESCUE_MAX_LAYERS=2                # Maksimal layer penyelamatan per setup (Strict Cap)
RESCUE_MIN_DISTANCE_PIPS=20        # Jarak minimum antar layer penyelamatan (2.0 USD pada Gold)
RESCUE_SCORE_THRESHOLD=1.60        # Ambang skor konsensus SPK untuk rescue entry
BASKET_TP_BUFFER_PIPS=18           # Target profit bersih di atas Average Break-Even (1.8 USD)
STAGNANT_HARVEST_ENABLED=true      # Panen cepat posisi stagnan
STAGNANT_HARVEST_SECONDS=180       # 3 menit: harvest jika profit >= $2.50
STAGNANT_TIME_DECAY_SECONDS=420    # 7 menit: salvage jika profit >= $0.50
MAX_HOLD_SECONDS=900               # 15 menit: batas maksimal penahanan posisi
```

---

## 6. Integrasi UI Dashboard (Cockpit & Control)

1. **Tab Positions di Cockpit:**
   - Menampilkan total posisi aktif beserta nomor tiket masing-masing, arah, ukuran lot, entry, harga saat ini, dan floating PnL secara live streaming.
   - Header tabel menampilkan ringkasan Basket: **`Total Lot`**, **`Avg Entry (BE)`**, dan **`Basket Net PnL`**.
2. **Panic Close All:**
   - Tombol darurat di Cockpit dan Control tetap berfungsi sebagai *failsafe manual* instan untuk melikuidasi seluruh posisi basket jika pengguna menginginkannya.
