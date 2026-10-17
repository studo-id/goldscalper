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
* **Dynamic Bleeding Clamp (Melirik Live Average Win):**
  - Alih-alih batas loss statis kaku, Juggler mengunci batas rugi maksimal per tiket secara adaptif:
    $$\text{Max Loss Limit} = 1.1 \times \text{Live Average Win Harian}$$
  - Jika live average win hari ini `$7.31` (atau `$5.49`), maka hard clamp dipasang otomatis di `-$8.04` (atau `-$6.04`). Posisi minus dipotong seketika tanpa kompromi, menghentikan pendarahan asimetris.
* **Duration-Tightened Cutloss (Waktu Berjalan 90s - 150s):**
  - Jika posisi minus telah berjalan > 90 detik tanpa adanya tanda pantulan (*reversal wick* M1), toleransi rugi dipangkas ke 60% clamp limit dan di-cutloss. Scalper tidak boleh membiarkan posisi minus menggantung menjadi trade harian.
* **Target-Proximity Take Profit (Melirik Sisa Target Harian):**
  - Jika floating profit posisi saat ini telah mencukupi $\ge 35\%$ dari sisa target harian akun, Juggler langsung mengeksekusi Take Profit seketika untuk mengamankan kemenangan hari itu.
* **Momentum-Decay Profit Harvest (60s - 120s):**
  - Begitu trade mengantongi $\ge 60\%$ dari Average Win harian dan momentum candle M1 melambat di detik 60–90, profit langsung dipanen (*Fast Salvage*).
* **Break-Even Pullback & Multi-Entry Modal Kecil:**
  - Maksimal posisi terbuka dibatasi ketat **1–3 posisi** (bukan 10 layer liar).
  - Titik Take-Profit keranjang ditarik ke **Average Entry + 3 pips buffer ($0.30)** untuk keluar impas/profit tipis secepatnya.
* **Post-Trade Cooldown Armor:**
  - Setelah terjadi cutloss clamp atau basket TP, sistem mengaktifkan jeda paksa **60–120 detik** untuk mencegah overtrading emosional ke dalam momentum berlawanan.

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
  - **Physical Noise Floor:** Menjamin batas cutloss pada lot berapapun selalu memiliki jarak nafas $\ge 16$ pips ($\$1.60$) pada Emas, dilindungi oleh *Grace Period* 15 detik awal agar tidak tercekik oleh spread broker.

### 4.2 Setup Grading & Risk-Free Pyramiding (Scale-In on Accurate Trends)

* **Golden Confluence (Setup Grade A+):**
  Mengadopsi prinsip konfluensi multi-indikator teruji (Bollinger Band Compression Squeeze + RSI Extreme Divergence <30/>70 + Micro-wick Rejection at Key Structure):
  - Ketika SPK mendeteksi konfluensi lintas divisi dengan Score $\ge 5.0$ dan Confidence $\ge 70\%$, setup diklasifikasikan sebagai **`GRADE A+ HIGH-CONVICTION`**.
  - Setup Grade A+ dibebaskan dari *double-shrinkage*, diberikan alokasi lot pemulihan **`0.03 – 0.04 lot`**, dan ditargetkan menyentuh TP Runner $\ge \$7.50$ s/d $\$15.00$ dengan rasio Payoff $\ge 1.5\text{x}$.
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
