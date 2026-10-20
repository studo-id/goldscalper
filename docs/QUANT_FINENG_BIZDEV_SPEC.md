# GoldScalper — Financial Engineering (The Juggler & Quant Lab) & BizDev Architecture Specification

**Version:** 2.0  
**Date:** 2026-10-15  
**Status:** Approved Operational Blueprint  
**System Identity:** High-Yield Small-Capital Sprint Engine (Companion to `AcengGold`)  
**Target Performance:** **30% – 40% Daily Growth Target** with Automated Circuit Breaker  
**Companions:** [PRD.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/PRD.md) · [BLUEPRINT.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/BLUEPRINT.md) · [MULTI_ENTRY_RESCUE_SPEC.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/MULTI_ENTRY_RESCUE_SPEC.md) · [DEPLOYMENT_SOP.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/DEPLOYMENT_SOP.md) · [IMPLEMENTATION_PLAN_INSTITUTIONAL_SMC.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/IMPLEMENTATION_PLAN_INSTITUTIONAL_SMC.md)

---

## 1. Executive Summary & Root-Cause Background

### 1.1 The Genesis & Missing Piece
GoldScalper dirancang untuk mengotomatiskan strategi manual berkinerja tinggi yang telah terbukti menghasilkan rata-rata **30% – 40% per hari pada modal kecil**. Selama ini, eksekusi manual tersebut membutuhkan konsentrasi intensif: memantau chart M1 tanpa henti dan menghitung silang formula spreadsheet kompleks untuk mengelola posisi terbuka (*juggling positions*).

Dalam pengujian live beberapa hari awal, bot dirasakan "belum pas". Diagnosa bedah kode menunjukkan dua kepingan vital yang belum terpasang:
1. **The Juggler (Financial Engineer)**: Bot saat ini hanya memiliki sinyal arah (BUY/SELL) dan exit reaktif, tetapi **buta terhadap target harian (30%–40%)** dan **tidak memiliki rem pengunci profit harian**. Ketika bot telah mencapai profit impresif di siang hari, ia terus membuka order hingga sesi malam sampai akhirnya keuntungan tersebut tergerus kembali (*giveback*).
2. **BizDev (Internal Unit Economics)**: Bot mengeksekusi volume perdagangan tinggi (*trade banyak*), namun tidak mengaudit aliran kas masuk dari **Rebate IB per lot** dan tidak memantau rasio biaya gesekan (*friction cost: spread + slippage*) yang menggerus profitabilitas modal kecil.

Dokumen ini mendefinisikan integrasi resmi **The Juggler** dan **BizDev** sebagai pengendali utama eksekusi modal kecil.

---

## 2. Arsitektur Hubungan Sistem (System Topology)

```
┌────────────────────────────────────────────────────────────────────────┐
│             ACENGGOLD (Workstation Windows PC - Core System)           │
│     Sistem Utama Institusional, Pengelola Modal Besar & Long-Term      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Companion Parallel Architecture
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             GOLDSCALPER (Home-Server Docker - Agile Speedboat)         │
│     Sistem Pendamping Khusus Modal Kecil ($50 - $200+)                 │
│     Misi: Sprint Agresif 30% - 40% Harian + Automated Circuit Breaker  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Pilar 1: Financial Engineering (The Juggler & Quant Lab)

Financial Engineering di GoldScalper beroperasi dalam dua mode:
* **The Juggler (Runtime Hot-Path Engine):** Mengambil alih kalkulasi spreadsheet manual secara real-time.
* **Quant Lab (Offline Analytics):** Mengaudit distribusi risiko ekstrim (*tail-risk*) dan kalibrasi parameter aman.

### 3.1 The Juggler: Otomatisasi Juggling Spreadsheet ke Kode

```
                    ┌──────────────────────────────────────────────┐
                    │          THE JUGGLER RUNTIME ENGINE          │
                    └──────────────────────┬───────────────────────┘
                                           │
         ┌─────────────────────────────────┼────────────────────────────────┐
         ▼                                 ▼                                ▼
┌─────────────────┐             ┌────────────────────┐            ┌───────────────────┐
│ Target-Seeking  │             │ In-Flight Position │            │ "DONE FOR THE DAY"│
│ Lot Sizing      │             │ Basket Mitigation  │            │ Circuit Breaker   │
│                 │             │                    │            │                   │
│ Hitung sisa $   │             │ Tarik Break-Even   │            │ Kunci brankas saat│
│ menuju 30%-40%  │             │ saat floating loss │            │ profit >= 35%     │
└─────────────────┘             └────────────────────┘            └───────────────────┘
```

#### 1. Target-Seeking Dynamic Lot Sizing
Tidak lagi menggunakan persentase lot statis. Juggler menghitung ukuran lot berdasarkan sisa jarak dolar menuju target harian:
$$\text{Target USD} = \text{Balance Awal Hari} \times (30\% \text{ s/d } 40\%)$$
$$\text{Remaining USD} = \text{Target USD} - \text{Realized PnL Hari Ini}$$
$$\text{Calculated Lot} = \text{Clamp}\left(\frac{\text{Remaining USD}}{\text{Expected Swing Points} \times \text{Tick Value}}, \text{Min Lot } 0.02, \text{Max Safe Lot } 0.10\right)$$
*Jika target harian tinggal sedikit (misal sisa \$5), lot otomatis mengecil guna meminimalisir risiko tersandung di garis akhir.*

#### 2. The Absolute Daily Profit Lock (Circuit Breaker Anti-Giveback)
* **Kondisi Trigger:** Ketika `Daily Net PnL` mencapai $\ge 30\%$ (atau target yang dikonfigurasi 35%–40%).
* **Aksi Seketika:**
  1. Menutup seluruh posisi aktif yang sedang profit.
  2. Mengaktifkan flag status sistem: **`STATE_LOCKED_DONE_FOR_THE_DAY`**.
  3. Memblokir 100% order baru dari SPK hingga pergantian tanggal kalender/sesi (00:00 UTC).
  4. Mengirimkan notifikasi selebrasi via PWA/Telegram:  
     *“Target 35% Harian Tercapai (+$XX.XX). Sistem dikunci aman. Selamat beristirahat, Boss!”*

#### 3. Asymmetric Hard Daily Loss Limit (Rem Darurat Kebangkrutan)
* Pada target profit harian 30%–40%, batas toleransi rugi harian dipatok maksimal **-15% s/d -20%**.
* Jika terkena hari buruk, bot berhenti total hari itu. Modal sisa 80%–85% masih sangat sehat untuk dilipatgandakan kembali esok hari tanpa terkena risiko *margin call*.

#### 4. In-Flight Position Mitigation & Dynamic SL/TP Matrix
* **Multi-Timeframe Watchdog (Satpam Bertingkat M1, M5, M15):**
  - Menggantikan batas waktu kaku (dumb timer 900 detik) dengan pengawasan 3-lapisan kecerdasan:
    - **Satpam Layer 1 (M1 Micro / Sniper):** `TF-M1-Sniper`, `Tech-EMA-Cross`, `Tech-RSI-Stoch` (memantau micro-rejection & adverse momentum).
    - **Satpam Layer 2 (M5 Swing Structure):** `TF-M5-Inspector`, `Struct-MarketStructure` (memantau swing structure CHoCH/BOS).
    - **Satpam Layer 3 (HTF Trend & Liquidity):** `TF-M15-Liquidity`, `TF-M30-Momentum`, `TF-H1-Regime`, `TF-H4-Structure`.
* **Smart Dynamic Time Extension (Pengganti 900s Dumb Timer):**
  - Saat durasi trade mencapai `max_hold_seconds`, sistem tidak langsung memotong buta.
  - Jika Satpam M5 dan HTF melapor bahwa struktur pasar masih sehat mendukung posisi (`SUPPORTING`), Juggler memberikan izin perpanjangan waktu (*Dynamic Time Extension* hingga +300 detik) untuk memberi ruang terbentuknya reversal menuju Take-Profit.
  - Jika Satpam melapor `NEUTRAL` atau `OPPOSING`, posisi langsung ditutup secara disiplin (`time_stop`).
* **Phase 0: M1 Candle Formation Grace Period (Nafas 60 Detik Pembentukan Candle):**
  - M1 memerlukan durasi penuh 60 detik untuk membentuk sebuah batang candle secara utuh (open, high, low, close).
  - Untuk mencegah posisi terpotong prematur oleh sumbu/ekor candle M1 palsu (*intra-candle noise/wick*), Juggler memberikan *Grace Period* minimum 60 detik (`watchdog_min_hold_seconds: 60`).
  - Selama `held < 60s`, cut-loss dini dilarang aktif KECUALI terjadi lonjakan bencana ekstrim riil (*catastrophic gap* $\ge 45-50$ pips / $\ge \$35-\$36$ pada lot 0.08). Fluktuasi normal lilin 15–25 pips dilindungi penuh agar tidak memotong prematur dan memberi ruang bagi Layer 2 Rescue untuk beroperasi jika diperlukan.
  - Sisi Take Profit (TP) **TETAP INSTAN / BEBAS** dieksekusi dalam hitungan detik (< 60s) saat target/momentum tercapai.
* **Satpam M1/M5 Dual Invalidation Cut & M5 Pattern Reversal Hold (Durasi $\ge 60$ Detik):**
  - **M5 Pattern Reversal Hold:** Jika durasi berjalan $\ge 60$ detik dan M1 berlawanan arah, namun Satpam M5 masih **`SUPPORTING`** (struktur swing M5 masih sehat), bot **DILARANG MEMOTONG SEPIHAK**. Posisi wajib ditahan (*Hold for M5 Reversal*) untuk memberikan ruang bagi pola candle M5 menyelesaikan pantulan menuju Take Profit.
  - **Dual Invalidation Cut:** Posisi HANYA dipotong dini jika **Satpam M1 dan Satpam M5 KEDUANYA KOMPAK `OPPOSING`** (terjadi konfirmasi *Break of Structure* / CHoCH di M5), memotong rugi di ambang batas aman (~$6-$8 / 40% clamp) sebelum menjemput full SL MT5.
* **Phase 3: Dynamic Hard Clamp & HTF Reversal Shield:**
  - Ambang batas cut loss dinamis standar: $\text{Base Clamp} = \max(\$7.00, \text{Live Avg Win} \times 1.1)$, dibatasi plafon ketat $1.35\times$ hard clamp (max $8.50 - $9.50).
  - **HTF Reversal Shield:** Jika tren besar (H4, H1, M30, M15) solid mendukung arah posisi (`SUPPORTING`), tarikan napas / pullback 10–18 pips dinilai sebagai koreksi wajar. Toleransi kerugian diperlebar menjadi $17.60 (22 pips pada lot 0.08) untuk mencegah pemotongan posisi searah tren besar dan memberi ruang bagi pembalikan arah menuju Take Profit.
* **Fast Break-Even Lock (BEP+ Zero-Risk Mode):**
  - Begitu posisi bergerak untung $\ge 12$ pips (atau profit $\ge \$1.80$), Stop Loss secara otomatis digeser ke `Entry + 0.10` (untuk BUY) atau `Entry - 0.10` (untuk SELL). Posisi yang sudah sempat hijau terkunci bebas risiko (*risk-free*) dan dilarang keras kembali menjadi merah. Jika tersentuh kembali, akun keluar dengan impas (minus tipis 17 sen akibat spread broker) tanpa kehilangan modal.
* **Solid Runner Harvest (Instant at Any Time):**
  - Kapan pun lonjakan harga menghasilkan profit runner solid ($\ge \$7.50$ atau $\ge 1.25\times \text{Live Avg Win}$), bot memanen Take Profit **SEKETIKA (INSTANT HARVEST)** tanpa terhambat oleh timer durasi 90 detik.
* **Defensive Momentum Harvest & Duration Stagnation (> 90s):**
  - Jika posisi telah berjalan $\ge 90$ detik dan HTF mulai berlawanan arah (`OPPOSING`), profit sekecil $\ge \$3.50$ langsung diselamatkan secara defensif sebelum momentum benar-benar berbalik.
* **Break-Even Pullback & Multi-Entry Modal Kecil:**
  - Maksimal posisi terbuka dibatasi ketat **1–2 posisi** (1 Initial + 1 Rescue Layer).
  - Titik Take-Profit keranjang ditarik ke **Average Entry + 3 pips buffer ($0.30)** untuk keluar impas/profit tipis secepatnya.
* **Post-Trade Cooldown Armor:**
  - Setelah terjadi cutloss clamp atau basket TP, sistem mengaktifkan jeda paksa **60–90 detik** untuk mencegah overtrading emosional ke dalam momentum berlawanan.

---

## 4. Pilar 2: Business Development (BizDev) untuk Scalping Frekuensi Tinggi

Pada gaya trading dengan jumlah trade banyak (*high trade frequency*), BizDev berperan sebagai arsitek keuangan internal yang mengubah volume transaksi menjadi laba bersih.

### 4.1 Ekstraksi Rebate IB sebagai Arus Kas Pasti
* Di broker Exness, trading XAUUSD menghasilkan komisi kemitraan (Rebate IB) berkisar **\$3.00 s/d \$8.00 per lot**.
* Pada strategi *trade banyak*, volume lot yang terputar per hari bisa mencapai 2.0 – 5.0 lot.
* **Nilai Ekonomi:**
  $$\text{Rebate Harian} = 3.0 \text{ Lot} \times \$6.00 = +\$18.00 \text{ USD / hari}$$
* Pada akun modal kecil (\$100), **+\$18.00 ini setara dengan +18% pertumbuhan akun pasif tambahan** yang dijamin masuk, terlepas dari hasil trade tersebut menang, kalah, atau impas (*break-even*).
* **Tugas BizDev:** Mencatat akumulasi rebate tick-by-tick dan menggabungkannya ke dalam metrik **Net Daily Yield**.

### 4.2 Friction Ratio Surveillance (Pengawal Biaya Broker)
BizDev memonitor efisiensi eksekusi broker secara real-time:
$$\text{Friction Cost} = \text{Spread Aktual} + \text{Komisi} + \text{Slippage Negatif}$$
$$\text{Friction Ratio} = \frac{\text{Total Friction Cost}}{\text{Gross Profit Generated}} \le 15\%$$
*Jika spread melebar di atas ambang batas (misal pre-news), BizDev memerintahkan Juggler untuk menunda entry karena biaya transaksi akan menggerus target harian.*

### 4.3 The Capital Sweeper (Amankan Modal Pokok)
* Strategi modal kecil agresif memiliki aturan emas: **Amankan uang asli secepat mungkin**.
* Ketika akun \$50 atau \$100 berhasil tumbuh mencapai +100% (modal berlipat dua), BizDev memunculkan sinyal rekomendasi penarikan (*Withdrawal Prompt*):  
  *“Modal awal \$50 telah aman. Silakan lakukan withdrawal \$50. Bot akan melanjutkan trading murni menggunakan profit broker (Free Rolling)!”*

### 4.4 In-Flight Reversal Arbiter & HTF Trend Alignment
* **Dilema Trader vs Solusi Kuantitatif:**
  Ketika posisi mengalami floating loss, trader manusia sering terjebak dalam "mudah-mudahan terjadi pembalikan (reversal)". Juggler menggantikan harapan emosional tersebut dengan **konsensus streaming dari para Higher Timeframe (HTF) Scouts dengan data candle kaya**:
  - `TF-H4-Structure` (H4 Trend & Major Order Blocks — bobot 2.5)
  - `TF-H1-Regime` (H1 21-EMA Slope & Box Channel — bobot 2.5)
  - `TF-M30-Momentum` (M30 Momentum & Exhaustion Wicks — bobot 1.5)
  - `TF-M15-Liquidity` (M15 Liquidity Sweeps & Structure — bobot 1.5)
  - `Struct-MarketStructure` (M5 Break of Structure / CHoCH — bobot 1.0)
* **Logika Keputusan Reversal:**
  - **`HTF_SUPPORTING` (Hold for Reversal):** Jika H4, H1, M30, M15 tetap searah dengan posisi, floating minus di M1 dinilai sebagai *minor pullback/retest*. Watchdog memberikan toleransi nafas hingga batas normal clamp untuk menunggu pembalikan arah kembali ke TP.
  - **`HTF_OPPOSING` (Early Cutloss — Do NOT Hope!):** Jika H1/M15/H4 telah mematahkan struktur berlawanan dengan posisi dan floating loss mencapai $\ge 65\%$ clamp, posisi **DIPOTONG SEGERA** tanpa menunggu tersentuh full SL.
  - **Physical Noise Floor & M1 Candle Grace Period:** Menjamin batas cutloss pada lot berapapun selalu memiliki jarak nafas $\ge 16$ pips ($\$1.60$) pada Emas, dilindungi oleh *M1 Candle Formation Grace Period* minimum 60 detik (`watchdog_min_hold_seconds: 60`) agar tidak tercekik oleh spread broker maupun sumbu (*wick*) candle M1 yang belum terbentuk utuh (*close*).

### 4.2 Setup Grading & Risk-Free Pyramiding (Scale-In on Accurate Trends)

* **Golden Confluence (Setup Grade A+):**
  Mengadopsi prinsip konfluensi multi-indikator teruji (Bollinger Band Compression Squeeze + RSI Extreme Divergence <30/>70 + Micro-wick Rejection at Key Structure):
  - Ketika SPK mendeteksi konfluensi lintas divisi dengan Score $\ge 5.0$ dan Confidence $\ge 70\%$, setup diklasifikasikan sebagai **`GRADE A+ HIGH-CONVICTION`**.
  - Setup Grade A+ dibebaskan dari *double-shrinkage*, diberikan alokasi lot pemulihan dengan multiplier hingga **`1.25x` (0.10 lot di saldo ~7k Cent)**, dan ditargetkan menyentuh TP Runner $\ge \$7.50$ s/d $\$15.00$ dengan rasio Payoff $\ge 1.5\text{x}$.
  - **Anti-Hunting Reversal SL Cushion:** Jarak Stop Loss fisik MT5 pada pembalikan arah diperlebar minimal $\ge 35$ pips ($\$3.50$) agar tidak terpicu prematur oleh gocekan sumbu (*wick hunting*) broker, menyerahkan keputusan cutloss dini kepada Juggler Watchdog secara cerdas.
* **Risk-Free Pyramiding (Scale-In saat Prediksi Terkonfirmasi Akurat):**
  - Jika posisi terbuka sedang running profit $\ge +20$ pips ($+\$2.00$) dan candle-candle berikutnya mengonfirmasi kelanjutan tren:
  - Bot diizinkan melakukan **entry tambahan (Layer 2)** searah tren.
  - **Mekanisme Pengunci Risiko:** Saat Layer 2 dieksekusi, Stop Loss posisi pertama **wajib digeser otomatis ke Break-Even (+0.20)** (`PYRAMID RISK-FREE LOCK`).
  - *Hasil FinEng:* Posisi pertama 100% bebas risiko rugi modal. Tambahan posisi kedua didanai murni oleh laba mengambang pasar (*house money*), melipatgandakan keuntungan gelombang tren secara aman.

---

## 5. Matriks Spesifikasi Teknis & Parameter Operasional

| Komponen | Parameter | Nilai Default | Logika / Fungsi |
|---|---|---|---|
| **Target** | `daily_profit_target_pct` | **30.0% s/d 40.0%** | Batas kemenangan harian sprint. |
| **Circuit Breaker** | `daily_profit_lock_enabled` | **True** | Kunci total sistem saat target tercapai. |
| **Stop Harian** | `max_daily_loss_pct` | **15.0%** | Rem darurat batas toleransi rugi harian. |
| **Multi-Entry** | `max_open_positions` | **3 Posisi** | Dibatasi khusus untuk ketahanan modal kecil. |
| **Sizing** | `lot_calculation_mode` | **TARGET_SEEKING** | Lot dihitung adaptif ke sisa target. |
| **Lot Floor / Cap** | `min_lot` / `max_lot` | **0.02 / 0.10** | Batas aman daya ungkit modal kecil. |
| **Basket Exit** | `basket_tp_buffer_pips` | **3.0 pips ($0.30)** | Jarak TP keranjang dari harga impas rata-rata. |
| **Time Decay** | `stagnant_harvest_seconds` | **120 detik** | Potong trade macet untuk selamatkan margin. |
| **BizDev** | `rebate_per_lot_usd` | **$6.00** | Kalkulator estimasi arus kas rebate harian. |
| **Friction Guard** | `max_friction_ratio_pct` | **25.0%** | Gating rasio gesekan biaya broker bersih (net friction setelah deduksi rebate $6/lot). Hanya memblokir trade pada status DEFENSE (drawdown harian < 0%); pada mode BALANCED/GROWTH memicu adaptasi TP expansion tanpa hard lock (anti deadlock paradox). |
| **SPK Floor Normal** | `min_confidence_floor_normal` | **0.25** | Ambang batas confidence baseline mode Balanced (0.25) & Growth (0.20). |
| **SPK Floor Defense** | `min_confidence_floor_defense` | **0.25 (s/d 0.30)** | Dinamis terhadap kedalaman drawdown; pnl_drag dibatasi maks -0.05 (anti double-penalty). |
| **Finish Line Floor** | `finish_line_confidence_floor` | **0.40** | Mengetatkan ambang SPK saat sisa target <= $20 guna mengunci kemenangan sprint. |
| **S/R Barrier Demotion** | `sr_barrier_confluence_min` | **5 confirming voters** | M1 micro S/R didemosi ke soft penalty (-0.12 s/d -0.18) saat konsensus kuat; tetap hard barrier saat Finish Line. |

---

## 6. Rencana Implementasi Kode (Engineering Steps)

1. **`config/settings.py`**:
   - Menambahkan field: `daily_profit_target_pct = 35.0`, `daily_profit_lock_enabled = True`, `max_daily_loss_pct = 15.0`, `max_open_positions = 3`.
2. **`execution/order_manager.py`**:
   - Menambahkan verifikasi status `is_daily_profit_locked()` sebelum mengeksekusi order dari SPK.
3. **`agents/divisions/risk/agents.py` (`PositionSizer` & `DrawdownGuard`)**:
   - Memodifikasi `PositionSizer` agar menerapkan formula `TARGET_SEEKING` berbasis sisa target dolar hari ini.
   - Menambahkan evaluasi pencapaian target harian pada `DrawdownGuard` untuk memicu *Daily Profit Lock*.
4. **`execution/position_manager.py`**:
   - Memastikan `max_open_positions = 3` di keranjang multi-entry dan mempercepat `basket_tp_buffer_pips = 3.0` untuk keluar cepat (*fast harvest*).
5. **Frontend Cockpit HUD**:
   - Menambahkan indikator target harian: Progress bar % menuju target 30%–40%, status pengunci brankas (`ACTIVE` / `LOCKED - DONE FOR THE DAY`), dan total estimasi rebate harian.

---

## 7. Indeks Dokumen Terkait

- **Kebutuhan Produk:** [PRD.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/PRD.md)
- **Arsitektur Sistem Docker:** [BLUEPRINT.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/BLUEPRINT.md)
- **Spesifikasi Defensive Recovery:** [MULTI_ENTRY_RESCUE_SPEC.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/MULTI_ENTRY_RESCUE_SPEC.md)
- **SOP Bridge MT5 Exness:** [DEPLOYMENT_SOP.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/DEPLOYMENT_SOP.md)
