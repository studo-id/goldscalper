# GoldScalper — Implementation Plan: Institutional SMC & Session Disciplines

**Version:** 1.0  
**Date:** 2026-10-17  
**Priority:** 🟡 HIGH — Strategic Alignment & Signal Quality Enhancement  
**Companions:**  
- [QUANT_FINENG_BIZDEV_SPEC.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/QUANT_FINENG_BIZDEV_SPEC.md)  
- [MULTI_ENTRY_RESCUE_SPEC.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/MULTI_ENTRY_RESCUE_SPEC.md)  
- [BLUEPRINT.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/BLUEPRINT.md)  
- [PRD.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/PRD.md)  
- [docs/riset/Kerangka Analisis Pasar Multi-Timeframe Emas.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/riset/Kerangka%20Analisis%20Pasar%20Multi-Timeframe%20Emas%20%28XAU_USD%29_%20Matriks%20Konfluensi%20dan%20Struktur%20Pasar%20Institusional.md)  
- [docs/riset/SOP Intraday XAU_USD.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/riset/SOP%20STANDAR%20PROSEDUR%20OPERASIONAL_%20EKSEKUSI%20TRADING%20INTRADAY%20XAU_USD%20BERBASIS%20STRUKTUR%20PASAR%20DAN%20MANAJEMEN%20RISIKO%20INSTITUSIONAL.md)

---

## 🎯 Tujuan & Filosofi Penyelarasan

Riset empiris menunjukkan bahwa keselarasan multi-timeframe 3 tingkat (Daily + H4 + H1) menghasilkan **Win Rate 71%**, **R:R 2.1:1**, dan **menekan angka Stop-Out hingga 29%**. Sebaliknya, trading tanpa keselarasan timeframe menghasilkan tingkat stop-out mencapai **71%**.

Tujuan dari rencana ini adalah memasang **filter institusional berkualitas tinggi (*Quality Signal Gate*)** tanpa merusak mekanisme operasional **The Juggler** (Target-Seeking lot sizing, dynamic bleeding clamp, & daily profit lock) serta **BizDev** (Friction surveillance & rebate capture).

```
┌────────────────────────────────────────────────────────────────────────┐
│  QUALITY GATE (Riset Institusional SMC & Top-Down)                     │
│  - D1/H4 Directional Veto: Haram melawan arus besar harian             │
│  - Order Block Body-Only Bounds (Open–Close) & FVG Confluence          │
│  - Session Clock: London 15m Freeze, 15:30 UTC Cutoff, 21:00 UTC Flat │
│  - News Blackout 30m Pre / 20m Post Event Window                       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Sinyal Lolos Verifikasi
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  THE JUGGLER & RISK GATE                                               │
│  - Target-Seeking Lot Sizing (Mengecil mendekati garis finish)         │
│  - Dynamic Bleeding Clamp (1.1x Live Avg Win)                          │
│  - Rem Brankas: Profit Harian >= 35% -> LOCK FOR THE DAY               │
│  - 3 Consecutive Losses Rule -> STOP FOR THE DAY                       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Posisi Aktif Berjalan
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│  EXECUTION & POSITION MANAGER                                          │
│  - Basket Mitigation & Break-Even Pullback (+3 pips)                   │
│  - Protected Pyramid Runners (Layer 2 bebas dari cutloss keranjang)    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 📋 Rincian Fase & Rencana Tugas (Task Breakdown)

### FASE 1: SINKRONISASI KONFIGURASI & PARAMETER RISIKO (Docs & Settings First)
**Goal:** Menstandarisasi parameter default agar selaras dengan SOP tanpa merusak fleksibilitas environment.

- [x] **Task 1.1 — Tambahkan Parameter Blackout & Session di `config/settings.py`:**
  - `news_blackout_pre_minutes: int = 30` (standar institusional: 30 menit sebelum).
  - `news_blackout_post_minutes: int = 20` (standar institusional: 20 menit setelah).
  - `london_open_freeze_enabled: bool = True` (bekukan entri 08:00–08:15 UTC).
  - `hard_cutoff_utc_enabled: bool = True` (hentikan entri baru setelah 15:30 UTC).
  - `overnight_flat_utc_enabled: bool = True` (tutup posisi mengambang sebelum 21:00 UTC).
  - Ubah `max_consecutive_losses: int = 3` (sebelumnya 4, diselaraskan dengan SOP).
- [x] **Task 1.2 — Sinkronisasi `.env.example`:**
  - Tambahkan dokumentasi nilai default baru di `.env.example`.
- [x] **Exit Criteria:** `python -c "from config.settings import settings; print(settings.news_blackout_pre_minutes, settings.max_consecutive_losses)"` mencetak `30 3`.

---

### FASE 2: TOP-DOWN BIAS & D1 MACRO DIRECTIONAL VETO
**Goal:** Menghilangkan eksekusi bunuh diri melawan tren besar Daily (Anti-Countertrend).

- [x] **Task 2.1 — Penguatan Bias D1 di `agents/divisions/timeframe/scouts.py` (`D1Macro`):**
  - Jika Daily terkonfirmasi **Bullish kuat** (posisi harga di atas EMA 50 dengan kemiringan positif dan struktur HH/HL): keluarkan `veto = VETO_SELL` (dilarang Short).
  - Jika Daily terkonfirmasi **Bearish kuat** (posisi harga di bawah EMA 50 dengan kemiringan negatif dan struktur LH/LL): keluarkan `veto = VETO_BUY` (dilarang Long).
  - Pertahankan proteksi *Extreme Zone* yang sudah ada: `EXTREME_PREMIUM` memveto BUY (anti-pucuk), `EXTREME_DISCOUNT` memveto SELL (anti-dasar).
  - Jika Daily berkonsolidasi (*Neutral/Contested*): bebaskan veto arah agar M15/H1 dan Juggler dapat melakukan micro-scalping / ping-pong range.
- [x] **Task 2.2 — Unit Test D1 Macro Directional Veto:**
  - Tambahkan test di `tests/test_timeframe_division.py` untuk memvalidasi penolakan SELL saat Daily Bullish dan penolakan BUY saat Daily Bearish.
- [x] **Exit Criteria:** Tes `test_d1_macro_bullish_vetoes_sell()` dan `test_d1_macro_bearish_vetoes_buy()` lolos 100%.

---

### FASE 3: ANATOMI ORDER BLOCK PRESISI (Body-Only Coordinates & Retest)
**Goal:** Mengganti aproksimasi kasar 2-candle dengan deteksi Order Block berbasis rentang badan lilin (*Open–Close*) dan *Displacement*.

- [x] **Task 3.1 — Refaktor Pemetaan Order Block di `agents/divisions/structure/agents.py` (`Liquidity`):**
  - Hitung zona horizontal Order Block **hanya dari rentang Open ke Close** lilin berlawanan arah sebelum terjadinya dorongan impulsif (*displacement* 3 lilin berturut-turut).
  - Tandai status zona: `is_fresh` (belum pernah disentuh), `is_retesting` (harga M5/M15 saat ini sedang menyentuh rentang body OB).
  - Pertahankan deteksi 3-candle Fair Value Gap (FVG) yang sudah ada: `bullish_fvg = b.lows[-1] > b.highs[-3]`.
  - Hasilkan metadata kaya: `ob_top`, `ob_bottom`, `ob_fresh`, `fvg_confluence`.
- [x] **Task 3.2 — Unit Test Order Block Body Bounds:**
  - Tambahkan pengujian di `tests/test_structure_division.py` untuk memastikan batas OB tidak menyertakan sumbu (*wick*).
- [x] **Exit Criteria:** `pytest tests/test_structure_division.py` lolos tanpa regresi.

---

### FASE 4: DISIPLIN JAM SESI & HARD CUTOFF (Session Clocks)
**Goal:** Membatasi eksekusi hanya pada jam-jam puncak likuiditas dan menghindari jebakan pembukaan London serta celah harga *overnight* (8–25 pips).

- [x] **Task 4.1 — Filter Observasi London Open (08:00–08:15 UTC) di `spk/veto.py` & `core/clock.py`:**
  - Pada 15 menit pertama sesi London (08:00–08:15 UTC), SPK mengeluarkan Hard Veto `LONDON_OPEN_OBSERVATION` untuk menunggu lilin M15 pertama mengonfirmasi breakout range Asia.
- [x] **Task 4.2 — Hard Cutoff 15:30 UTC di `spk/veto.py`:**
  - Mulai pukul 15:30 UTC s/d 21:00 UTC, SPK menolak seluruh order baru dengan alasan `SESSION_HARD_CUTOFF_1530_UTC`. Posisi yang sudah terbuka tetap dikawal hingga TP/trailing/clamp.
- [x] **Task 4.3 — Daily Overnight Flat Monitor di `execution/position_manager.py`:**
  - Jika waktu menyentuh pukul 21:00 UTC dan masih ada posisi terbuka, bot menutup posisi secara aman untuk mencegah risiko lonjakan spread dan gap malam hari.
- [x] **Task 4.4 — Unit Test Sesi & Cutoff:**
  - Tambahkan unit test di `tests/test_clock.py` dan `tests/test_spk_veto.py` untuk menguji trigger penolakan di jam 08:05 UTC dan 16:00 UTC.
- [x] **Exit Criteria:** SPK memveto order di jam terlarang secara deterministik.

---

### FASE 5: SINKRONISASI DOKUMENTASI & PENGUJIAN AKHIR
**Goal:** Mematuhi hukum mutlak dokumentasi ([AGENTS.md Section 3](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/AGENTS.md)) dan menjamin kesiapan live di server.

- [x] **Task 5.1 — Pembaruan Companion Documents:**
  - Update [docs/PROGRESS.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/PROGRESS.md) (Log kronologis).
  - Update [docs/PRD.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/PRD.md) & [docs/BLUEPRINT.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/BLUEPRINT.md) (Menautkan dokumen rencana ini).
  - Update [docs/QUANT_FINENG_BIZDEV_SPEC.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/QUANT_FINENG_BIZDEV_SPEC.md) (Penegasan hierarki Quality Gate vs Juggler Gate).
- [x] **Task 5.2 — Validasi Seluruh Test Suite (Remote Docker):**
  - Jalankan `pytest -q` pada container `gs-bot` di remote server (`studo@100.114.150.48`). Pastikan 230+ test passing 100%.
- [x] **Task 5.3 — Deploy & Live Verification:**
  - Deploy kode dan berkas dokumentasi ke server via script deploy, cek endpoint `/health` dan log runtime.
- [x] **Exit Criteria:** Sistem live beroperasi dengan log bersih, tanpa kabel putus atau anomali.
