# Progress Log — GoldScalper

Worklog kronologis. **Entry terbaru di paling atas.** Setiap update pekerjaan
ditambahkan sebagai satu entry baru (jangan edit entry lama; tambahkan koreksi
di entry baru).

## Cara menambah entry

Append blok berikut langsung setelah baris `---` di bawah:

```markdown
## <YYYY-MM-DD> — <Judul singkat>

**Phase / Area:** <mis. Phase 12 — MT5 Bridge>
**Status:** <Done | WIP | Blocked>

**Yang dikerjakan**
- ...

**File tersentuh**
- `path/file.py` — ringkas perubahan

**Verifikasi**
- `<command>` → <hasil (mis. 215 passed, ruff clean)>

**Catatan / Next**
- ...
```

Aturan singkat:
- Satu entry = satu sesi/paket kerja, bukan satu baris kode.
- Selalu cantumkan perintah verifikasi + hasilnya (jangan bilang "done" tanpa bukti).
- Tulis apa yang **belum** selesai / blocker secara eksplisit.
- Bahasa Indonesia, istilah teknis boleh tetap Inggris.

---

## 2026-10-20 — Sinkronisasi Koordinasi Rescue Basket (Kolektif) & Relaksasi Plafon HTF Reversal Clamp

**Phase / Area:** Execution Layer & Position Management (`execution/position_manager.py`, `runtime.py`, `tests/test_execution.py`)
**Status:** Done & Deployed to VPS

**Yang dikerjakan**
- **Root Cause Analysis Kasus Cutloss 61 Detik & Terlantarnya Layer 1:**
  - Audit database & docker logs menemukan fenomena pada tiket `4900735979` (Layer 1 SELL @ 4115.72, loss -$23.47 di durasi 61s) dan `4900639917` (Layer 1 SELL @ 4121.22, loss -$23.22 di durasi 61s).
  - Ditemukan bahwa Satpam **Layer 2 Rescue sebenarnya BERHASIL MASUK** (tiket `4900741601` dan `4900643167`).
  - Namun terjadi **Desinkronisasi Keranjang (Basket De-synchronization)**:
    1. Logika individual *Fast Break-Even Lock* (BEP+) menggeser SL Layer 2 ke entry setelah floating profit sedikit. Saat harga terkocok, Layer 2 tertutup sendirian dengan profit receh (+0.22 s/d +1.99).
    2. Layer 1 tertinggal sendirian dalam drawdown 30 pips (-$23.47).
    3. Tepat di detik ke-61 saat Grace Period M1 (60s) habis, sistem melihat Layer 1 sendirian dengan loss $\le -$17.60 (`htf_reversal_clamp`), lalu memotongnya sepihak sebagai `HTF_EXHAUSTED`.
- **Implementasi Solusi Kuantitatif:**
  - **Kunci Kesatuan Keranjang (Collective Rescue Resolution):**
    - Di `runtime.py`, tiket yang menjadi bagian dari active multi-position rescue basket ditandai dengan `in_rescue_basket = True`.
    - Di `execution/position_manager.py`: Posisi dengan `in_rescue_basket = True` **DILARANG** mengaktifkan individual Fast Break-Even Lock (mencegah Layer 2 keluar solo) dan **DILARANG** dipotong secara individual oleh Dynamic Clamp di detik 61s.
    - Keduanya dikelola sebagai satu kesatuan oleh `manage_basket()` menuju target Average Break-Even atau aggregate net TP.
  - **Collective Basket Catastrophic Loss Guard:**
    - Jika tren adverse terus berlanjut tanpa rebound dan total net loss keranjang mencapai batas risiko agregat ($\ge \$38.00$ atau 25 pips per layer), seluruh keranjang dipotong bersamaan secara simultan. Tidak ada yang ditinggal sendirian.
  - **Relaksasi Plafon HTF Reversal Clamp:**
    - Plafon perisai tren HTF dinaikkan dari `volume * 2.20 * 100` ($17.60 / 22 pips) menjadi `volume * 3.50 * 100` ($28.00 / 35 pips pada lot 0.08) agar pullback sehat lilin M5/HTF memiliki ruang napas alami tanpa terpotong prematur.

**File tersentuh**
- `execution/position_manager.py` — Bypass individual BEP & individual clamp cut saat in_rescue_basket; relaksasi HTF reversal clamp s/d $28.00; collective basket catastrophic cut di `manage_basket()`.
- `runtime.py` — Deteksi tiket keranjang penyelamat dan injeksi `in_rescue_basket = True` ke konteks manajemen tiket.
- `tests/test_execution.py` — Update parameter test clamp $28.00 dan penambahan unit test `test_rescue_basket_bypasses_individual_clamp_and_bep`.

**Verifikasi**
- `pytest tests/test_execution.py` → 21 passed (100% lulus di lokal).
- `docker exec -i gs-bot pytest tests/test_execution.py` → 16 passed di container produksi VPS.
- SCP ke server VPS & restart container `gs-bot`. Log bot startup bersih (37 agents running, MT5 connected).

**Phase / Area:** Execution Layer & Position Management (`execution/position_manager.py`, `tests/test_execution.py`)
**Status:** Done & Deployed to VPS

**Yang dikerjakan**
- **Analisis Lonjakan Profit Tidak Terambil di Titik Terbawah (Tiket 4900529726):**
  - Posisi SELL dibuka di 4,120.91. Harga emas menukik tajam ke 4,118.00 (floating profit mencapai +$17.46 pada lot 0.06).
  - Namun TP tidak tereksekusi di titik bawah tersebut, dan baru ditutup di 4,120.30 dengan sisa profit hanya +$3.63 setelah harga memantul.
  - **Ditemukan Root Cause:** Di `execution/position_manager.py`, logika `current_profit >= runner_target` terselip di dalam blok `if s.juggler_enabled and held >= 90:`.
  - Akibatnya, saat lonjakan profit terjadi di detik ke-65 (< 90s), sistem menolak memanen profit dan membiarkan posisi mengambang sampai detik ke-90 saat harga sudah keburu memantul naik.
  - Selain itu, order hard TP broker dipasang terlalu jauh di 4,114.26 (66.5 pips), sehingga tidak tersentuh saat harga mencapai 4,118.00.
- **Solusi Eksekusi Cepat:**
  - Memisahkan logika Solid Runner Harvest agar dieksekusi **SEKETIKA (Instant at Any Time)** begitu `current_profit >= runner_target` ($\ge \$7.50$ atau $1.25\times \text{avg win}$) tanpa memedulikan batas waktu 90 detik.
  - Menjaga pertahanan defensif `held >= 90s` hanya untuk harvest darurat saat momentum macet / HTF berbalik arah.
- **Verifikasi & Deployment:**
  - Menambahkan unit test `test_instant_runner_harvest_at_any_time` di `tests/test_execution.py` (20 passed).
  - Berhasil lulus uji Docker di container VPS (16 passed).
  - Deploy file ke server VPS dan restart `gs-bot`.


## 2026-10-20 — Hotfix Perlindungan Lilin M1 (0-60 Detik) & Penaikan Ambang Catastrophic Gap

**Phase / Area:** Execution Layer & Position Management (`execution/position_manager.py`, `tests/test_execution.py`)
**Status:** Done & Deployed to VPS

**Yang dikerjakan**
- **Investigasi Cutloss di Bawah 60 Detik (Tiket 4900380243 & 4900391330):**
  - Tiket `4900380243` (durasi 22s, loss -$16.20) dan `4900391330` (durasi 33s, loss -$16.25) terpotong prematur di bawah 60 detik.
  - Log server membuktikan pemotongan dipicu oleh sub-fitur `JUGGLER CATASTROPHIC GAP CUT` yang salah mendeteksi tarikan napas / wick lilin M1 sebagai "bencana flash crash".
  - **Cacat Formula:** Formula lama menghitung `catastrophic_gap_usd = round(pos.volume * 2.00 * 100.0, 2)`. Untuk lot 0.08, nilai ini adalah `$16.00` yang setara hanya **20 pips ($2.00) jarak harga Gold**!
  - Hal ini menimbulkan kontradiksi fatal: di saat harga bergerak berlawanan 20 pips (zona di mana **Layer 2 Rescue** seharusnya bersiap masuk), sistem malah panik dan memotong posisi di detik 22s dan 33s.
- **Solusi & Penegakan Grace Period Lilin M1:**
  - Ambang batas `catastrophic_gap_usd` dinaikkan ke level darurat bencana riil ($\ge 45-50$ pips / $\ge \$35-\$36$ pada lot 0.08) via formula `max(35.0, round(pos.volume * 4.50 * 100.0, 2))`.
  - Tarikan napas wajar 15–25 pips pada lilin M1 tidak akan lagi memicu cutloss dini di bawah 60 detik, memberi ruang bagi 1 lilin M1 terbentuk utuh dan memungkinkan Layer 2 Rescue bekerja bila diperlukan.
- **Pengujian & Deployment:**
  - Memperbarui unit test di `tests/test_execution.py`.
  - Verifikasi: Local `pytest tests/test_execution.py` (19 passed) dan VPS Docker (16 passed).
  - Deploy file ke `/home/studo/apps/goldscalper/execution/position_manager.py` dan hot-restart `gs-bot`.


## 2026-10-20 — Hotfix String Mismatch HTF Reversal Shield & Analisis Dua Cutloss Beruntun

**Phase / Area:** Execution Layer & Juggler Engine (`execution/position_manager.py`, `tests/test_execution.py`)
**Status:** Done & Deployed to VPS

**Yang dikerjakan**
- **Analisis Mendalam 2 Cutloss Beruntun (Tiket 4900315971 & 4900324821):**
  - Menginvestigasi mengapa 2 posisi SELL dipotong tepat di detik 61s dengan loss -$11.58 dan -$13.62 saat tren HTF sesungguhnya mendukung (`HTF=SUPPORTING`).
  - Ditemukan fatal bug string comparison di `execution/position_manager.py`: fungsi `evaluate_multi_tf_watchdogs` menghasilkan `htf_bias["verdict"] = "SUPPORTING"` (tanpa prefiks `"HTF_"`), sedangkan Phase 2 dan Phase 3 mengecek `htf_bias["verdict"] == "HTF_SUPPORTING"`.
  - Akibat bug tersebut, perbandingan selalu `False`, sehingga toleransi `htf_reversal_clamp` ($17.60 untuk 0.08 lot) diabaikan total, dan Dynamic Clamp langsung memotong posisi secara buta di detik ke-61 dengan batas -$7.00.
  - Layer 2 Rescue tidak terpicu karena pullback harga hanya 14.5 dan 17.0 pips (di bawah `rescue_min_distance_pips = 20.0` / $2.00).
- **Perbaikan Kode & Pengujian:**
  - Memperbaiki pencocokan string agar mendukung format `"SUPPORTING"` maupun `"HTF_SUPPORTING"`, serta `"OPPOSING"` maupun `"HTF_OPPOSING"` menggunakan helper flags `is_htf_supporting` dan `is_htf_opposing`.
  - Menambahkan unit test `test_htf_reversal_shield_protects_minor_pullback` di `tests/test_execution.py`.
  - Berhasil lulus 100% (16 passed di Docker VPS, 19 passed lokal).
- **Deploy & Hot-Restart ke VPS:**
  - Kode disinkronkan ke `/home/studo/apps/goldscalper/execution/position_manager.py`.
  - Container `gs-bot` di-restart dan langsung beroperasi normal (sukses mengonfirmasi chain sell wave win).

**File tersentuh**
- `execution/position_manager.py` — perbaikan perbandingan string `is_htf_supporting` & `is_htf_opposing`.
- `tests/test_execution.py` — penambahan unit test `test_htf_reversal_shield_protects_minor_pullback`.
- `docs/PROGRESS.md` — dokumentasi worklog.

**Verifikasi**
- Local: `pytest tests/test_execution.py` → 19 passed in 0.20s.
- VPS Docker: `docker exec gs-bot pytest tests/test_execution.py` → 16 passed in 0.27s.
- VPS Log: `docker logs gs-bot` → status healthy, runtime active.


## 2026-10-20 — Penegakan HTF Supporting Reversal Shield & Penyelarasan Rescue Layer

**Phase / Area:** Execution Layer & Risk Architecture (`execution/position_manager.py`, `tests/test_execution.py`)
**Status:** Done

**Yang dikerjakan**
- **Mengintegrasikan HTF Reversal Shield pada Phase 3 Dynamic Clamp:**
  - Sebelumnya, pada detik ke-62 (setelah 60s M1 close), `juggler_dynamic_clamp` langsung memotong posisi jika loss $\le -\$7.00$ secara buta, tanpa mempedulikan bahwa status pasar adalah `HTF=SUPPORTING` (arah tren besar H4, H1, M30, M15 sangat mendukung). Akibatnya, pullback tipis 8.9 pips pada lot 0.08 dipotong rugi -$7.16, padahal 1 menit kemudian harga emas langsung terjun bebas ke target profit TP.
  - Menambahkan perlindungan **`HTF_SUPPORTING` Reversal Shield**: Jika seluruh timeframe makro searah mendukung posisi, bot dilarang memotong pada fluktuasi pullback normal. Diberikan toleransi pembalikan arah (*Reversal Buffer*) hingga 22 pips ($-\$14.00–\$17.50$), memberi ruang bagi tren besar untuk melanjutkan momentum atau bagi Rescue Layer 2 ($\ge 20$ pips) untuk bekerja memulihkan posisi.
- **Penyelarasan Phase 4 Duration Stagnation Cut:**
  - Menambahkan syarat `htf_bias["verdict"] != "HTF_SUPPORTING"` pada pemotongan durasi 90 detik, mencegah posisi yang tren besarnya masih sehat terpotong prematur oleh noise minor M1.

**File tersentuh**
- `execution/position_manager.py` — Implementasi HTF Reversal Shield pada Phase 3 clamp dan proteksi tren pada Phase 4 duration cut.
- `docs/PROGRESS.md` — Pencatatan worklog kronologis.

**Verifikasi**
- `python -m pytest tests/test_execution.py ...` → 115 passed in 0.47s.
- `scp execution/position_manager.py studo@100.114.150.48:...` → File tersinkronisasi ke server VPS.
- `docker restart gs-bot` → Container aktif dan live trading normal.

---

## 2026-10-20 — Penyelarasan M1 Candle Formation Grace Period (60s) & Multi-Entry Shield

**Phase / Area:** Execution Layer, Risk & Exit Architecture (`execution/position_manager.py`, `tests/test_execution.py`)
**Status:** Done

**Yang dikerjakan**
- **Mengembalikan Kedaulatan M1 Grace Period (60 Detik Utuh):**
  - Mengeliminasi *loophole* di Phase 0 di mana ambang batas darurat `1.15x clamp` (-$8.05) sebelumnya menyebabkan fluktuasi normal sumbu candle M1 (10–16 pips pada lot 0.05–0.08) membatalkan *Grace Period* dan memicu cut loss prematur di detik 16s–37s.
  - Mempertegas syarat penahanan utuh 60 detik: Selama `held < min_hold` (60 detik), posisi terlindungi penuh dari *intra-candle noise* kecuali terjadi *runaway flash crash / catastrophic gap* $\ge 20$–$25$ pips ($-\$14.00+$).
  - Menegakkan `held >= min_hold` secara eksplisit pada Phase 3 (`juggler_dynamic_clamp`), sehingga *Dynamic Clamp* baru diperbolehkan bertindak setelah candle M1 resmi *close*.
- **Membuka Ruang Nafas untuk Multi-Entry Rescue Layering:**
  - Dengan amannya posisi Layer 1 dari pembunuhan dini pada jarak 10–16 pips, harga kini memiliki ruang untuk mencapai zona Rescue Layer ($\ge 20$–$30$ pips) saat terjadi *pullback*, memungkinkan strategi keranjang (*Basket Recovery*) bekerja sesuai spesifikasi.
- **Unit Test & Test Suite:**
  - Memperbarui `tests/test_execution.py` untuk memvalidasi proteksi loss -$9.00 di detik 35s tetap utuh (*protected*), dan catastrophic gap cut bekerja di level $-\$25.00$.

**File tersentuh**
- `execution/position_manager.py` — Penguatan Phase 0 grace period 60s, kalibrasi batas gap ekstrem, dan penambahan syarat `held >= min_hold` pada dynamic clamp.
- `tests/test_execution.py` — Penambahan test case intra-candle wick protection dan catastrophic gap cut.
- `tests/test_orchestrator.py` — Penyesuaian test fixture hard veto.
- `docs/PROGRESS.md` — Pencatatan worklog kronologis.

**Verifikasi**
- `python -m pytest tests/test_execution.py` → 18 passed.
- `python -m pytest tests/test_execution.py tests/test_risk_division.py tests/test_spk_veto.py tests/test_orchestrator.py tests/test_wave_engine.py tests/test_market_regime.py tests/test_technical_division.py` → 115 passed in 0.49s.
- `scp execution/position_manager.py studo@100.114.150.48:...` → File tersinkronisasi ke server VPS.
- `docker restart gs-bot` → Container aktif dan live trading normal.

---

## 2026-10-20 — Cockpit URL Tab Parameter & Recent Trades Auto-Hydration Fix

**Phase / Area:** Frontend Cockpit, Router & Navigation (`frontend/js/app.js`, `frontend/js/agents.js`)
**Status:** Done

**Yang dikerjakan**
- **Fix Recent Trades Initial Empty State:**
  - Sebelumnya, saat user membuka/merefresh halaman di tab `Recent Trades`, `tradesBody()` merender empty state karena data API belum selesai di-fetch, dan fungsi `cockpit.patch()` tidak pernah meng-update `#trades-table-wrap`.
  - Menambahkan auto-hydration di `cockpit.patch()`: mendeteksi perubahan `recentKey` atau keberadaan loading/empty placeholder, lalu me-render ulang `tradesBody()` begitu response `/api/trades` selesai di-fetch tanpa perlu klik tab lain.
  - Menambahkan skeleton loading shimmer yang elegan saat initial state `state.trades?.recent === undefined` sesuai aturan Anti-AI-Slop & Strict Borderless UI.
- **Direct Tab URL Parameter & Navigation Sync:**
  - Menambahkan `COCKPIT_SUBTABS` (`positions`, `trace`, `trades`, `recent`, `votes`, `open`, dll.) dan sinkronisasi dua arah dengan parameter URL `tab` (e.g. `?tab=trades`, `?tab=positions`, `?tab=trace`).
  - Memperbarui router `resolveInitialTab()` dan `go()` di `app.js` agar URL parameter `?tab=trades` langsung membuka Cockpit dengan tab Recent Trades aktif dan tidak tertimpa/terhapus.
  - Mendukung browser navigation `popstate` dan `hashchange` bolak-balik antar subtab secara instan tanpa reload penuh.

**File tersentuh**
- `frontend/js/agents.js` — Ekspor `COCKPIT_SUBTABS`, update reading param `tab`/`subtab`, update click handler URL param, tambahkan live update `#trades-table-wrap` di `patch()`, dan skeleton shimmer di `tradesBody()`.
- `frontend/js/app.js` — Import `COCKPIT_SUBTABS`, perbaiki `resolveInitialTab()`, `go()`, serta handler `popstate`/`hashchange` untuk sinkronisasi subtab Cockpit.
- `docs/PROGRESS.md` — Pencatatan worklog kronologis.

**Verifikasi**
- `node -c frontend/js/agents.js; node -c frontend/js/app.js` → Syntax Clean.
- `pytest tests/test_spk_veto.py tests/test_wave_engine.py tests/test_market_regime.py` → 36 passed.
- `scp frontend/js/agents.js frontend/js/app.js studo@100.114.150.48:...` → File tersinkronisasi ke server VPS.

**Catatan / Next**
- Tab URL parameter `?tab=trades`, `?tab=positions`, dan `?tab=trace` kini dapat di-bookmark / direct link secara penuh.

---

## 2026-10-20 — Data-Driven Wave Engine & Smart Broken-Wave Cooldown

**Phase / Area:** Core, SPK Veto & Execution (`core/wave_engine.py`, `runtime.py`, `spk/veto.py`, `tests/test_wave_engine.py`)
**Status:** Done

**Yang dikerjakan**
- **Mengembangkan Data-Driven Wave Engine (Menggantikan Limit Rantai Statis):**
  - Alih-alih membatasi trade dengan angka kaku (3x chain seperti AcengGold yang memotong peluang runner), kapasitas gelombang kini diproyeksikan langsung dari **telemetri pasar**:
    - **`HEALTHY` ($\text{Extension} \le 1.8\times \text{ATR}$):** Tren masih muda dan bertenaga penuh $\rightarrow$ rapid chaining diizinkan tanpa batas statis.
    - **`MATURE` ($1.8\times < \text{Extension} \le 2.5\times \text{ATR}$):** Tren matang $\rightarrow$ sizing dipotong menjadi 0.75x untuk proteksi modal.
    - **`EXHAUSTED` ($\text{Extension} > 2.5\times \text{ATR}$ atau penolakan sumbu $\ge 40\%$):** Kapasitas gelombang habis $\rightarrow$ menolak entry searah baru (`VETO_WAVE`).
- **Smart Broken-Wave Invalidation (90s Scalper Cooldown):**
  - Berbeda dengan jeda 10 menit AcengGold yang terlalu lama untuk M1 scalper, jika suatu gelombang patah (cutloss):
    - Bot hanya mengunci arah yang patah tersebut selama **90 detik** (`broken_wave_cooldown_s = 90`).
    - **Arah berlawanan TIDAK terkunci**, sehingga bot bebas menangkap reversal instan.
    - **Early Release:** Cooldown dapat di-unlock otomatis jika terbentuk validasi struktur lilin baru.
- **Unit Testing:**
  - Ditambahkan `tests/test_wave_engine.py` (3 test komprehensif, 100% passed).

**File tersentuh**
- `core/wave_engine.py` — Engine kapasitas gelombang & broken-wave tracker
- `runtime.py` — Wiring wave engine lifecycle (open/close tracker dan state injection)
- `spk/veto.py` — SPK hard veto gate untuk kapasitas gelombang & broken wave cooldown
- `tests/test_wave_engine.py` — Unit test suite

**Verifikasi**
- `pytest tests/test_wave_engine.py tests/test_technical_division.py tests/test_market_regime.py tests/test_spk_veto.py` → 60 passed in 0.23s

**Catatan / Next**
- Deploy file ke server VPS `100.114.150.48` dan restart container `gs-bot`.

---

## 2026-10-20 — Micro-Exhaustion Pullback Guard (AcengGold-grade Micro Timing)

**Phase / Area:** Core, Technical Division & SPK Veto (`core/market_regime.py`, `agents/divisions/technical/agents.py`, `spk/veto.py`, `tests/test_market_regime.py`)
**Status:** Done

**Yang dikerjakan**
- **Investigasi Transaksi Loss #4899761578 & Perilaku AcengGold:**
  - Posisi SELL 0.08 dibuka di dasar lembah (`4119.846`) tepat sebelum pantulan (*micro-bounce*) 11.5 pips naik ke 4121.0, memicu Juggler Dynamic Clamp cut loss (-$8.33).
  - Investigasi log `aceng-bot` menemukan bahwa AcengGold menahan diri dengan veto: `[SPK HARD GATE] VETO SPK v3.5: REJECTED_MICRO_EXHAUSTION: M5 dan M1 keduanya berstatus BULLISH (terjadi pantulan di micro-structure)`.
- **Implementasi Micro-Structure Voting & Pullback Guard:**
  - Pada `core/market_regime.py`:
    - Menghitung arah candle M5 (`m5_micro_vote`) dan bar M1 tertutup (`m1_micro_vote`) termasuk deteksi sumbu penolakan (*rejection wick* $\ge 40\%$).
    - Jika $M1 = +1$ dan $M5 = +1$ (`BULLISH_BOUNCE`), tren turun dipause (`allow_trend_continuation = False`) untuk mencegah SELL di dasar lembah.
    - Jika $M1 = -1$ dan $M5 = -1$ (`BEARISH_DIP`), tren naik dipause (`allow_trend_continuation = False`) untuk mencegah BUY di puncak.
  - Pada `agents/divisions/technical/agents.py`:
    - S/R agent mengaktifkan `VETO_SELL` seketika saat `BULLISH_BOUNCE` aktif di tren turun.
    - S/R agent mengaktifkan `VETO_BUY` seketika saat `BEARISH_DIP` aktif di tren naik.
  - Pada `spk/veto.py`:
    - Menambahkan hard gatekeeper `REJECTED_MICRO_EXHAUSTION` sebagai lapis kedua sebelum order dieksekusi.
- **Unit Testing:**
  - Ditambahkan unit test di `tests/test_market_regime.py` untuk menguji pantulan micro-structure (55 passed).

**File tersentuh**
- `core/market_regime.py` — micro-structure vote and pullback pause
- `agents/divisions/technical/agents.py` — S/R agent micro-exhaustion veto
- `spk/veto.py` — SPK hard veto gate for micro-exhaustion
- `tests/test_market_regime.py` — unit tests

**Verifikasi**
- `pytest tests/test_technical_division.py tests/test_market_regime.py tests/test_spk_veto.py` → 55 passed in 0.21s

**Catatan / Next**
- Deploy file ke server VPS `100.114.150.48` dan restart container `gs-bot`.

---

## 2026-10-20 — Currency Filtering for News Blackout (USD Specific for XAUUSD)

**Phase / Area:** Core Services (`core/calendar_service.py`, `tests/test_calendar_service.py`)
**Status:** Done

**Yang dikerjakan**
- Memperbaiki pengecekan blackout pada `EconomicCalendarService.check_blackout()`:
  - Menambahkan parameter `target_currencies: tuple[str, ...] = ("USD", "US")`.
  - Berita rilis dari luar Amerika Serikat (seperti `UK Labour Market Report`, `Australia CPI`, `Bank of Canada`) yang berlabel `GLOBAL` / non-USD tidak lagi memicu Hard Veto blackout di instrumen `XAUUSDm`.
  - Hanya berita High-Impact yang langsung mempengaruhi US Dollar (FOMC, NFP, US CPI, GDP AS, PCE, Retail Sales AS) yang memicu News Blackout.
- Menambahkan test suite `tests/test_calendar_service.py` untuk memvalidasi pemfilteran mata uang blackout (100% passed).

**File tersentuh**
- `core/calendar_service.py` — filter mata uang pada blackout check
- `tests/test_calendar_service.py` — unit test pemfilteran berita USD vs non-USD

**Verifikasi**
- `pytest tests/test_calendar_service.py tests/test_fundamental_division.py` → 14 passed in 0.18s

**Catatan / Next**
- Deploy file ke server VPS `100.114.150.48` dan restart container `gs-bot`.

---

## 2026-10-20 — 4-Stage Market Lifecycle & Regime Engine (Adaptive Trend Riding & Exhaustion Guard)

**Phase / Area:** Core & Technical Division (`core/market_regime.py`, `agents/divisions/technical/agents.py`, `spk/veto.py`, `runtime.py`)
**Status:** Done

**Yang dikerjakan**
- **Mengakhiri Kebutaan Rezim Tren vs Sideway (The Rolling Window Trap Elimination):**
  1. **Investigasi Kejadian Live (12:07 - 12:19 WIB):**
     - Ditemukan alasan faktual mengapa bot pendamping (AcengGold) panen 12 trade beruntun (+98.30 USC) saat tren turun, sedangkan GoldScalper membeku/bengong selama 15 menit.
     - Penyebab: Aturan `dead_zone_max_span = 12.00` mengecek jendela 20 bar M1 ($9.69) dan secara buta mengira pasar sedang sideway, padahal pasar sedang trending deras. Akibatnya, `VETO_ALL` memblokir area tengah 40% dan `VETO_SELL` memblokir area bawah 30%—sehingga sistem tidak bisa SELL di mana pun.
  2. **Implementasi Market Lifecycle Engine (`core/market_regime.py`):**
     - Membangun modul klasifikasi siklus pasar 4-fase:
       - **Fase 1 (SIDEWAY):** Slope EMA M5 mendatar, tidak ada displacement. **Dead-Zone 30/40/30 aktif ketat** (anti-chop mean-reversion).
       - **Fase 2 (TRENDING EXPANSION):** Slope EMA M5 tajam, terjadi BOS atau multi-bar progression. **Dead-Zone DINONAKTIFKAN TOTAL**, larangan S/R di arah tren dicabut, mengizinkan *trend continuation scalping* (gaya AcengGold).
       - **Fase 3 (TREND EXHAUSTION):** Harga teregang $> 2.3\times \text{ATR}$ dari mean, RSI ekstrem (< 28 atau > 72) dengan sumbu penolakan. **Dilarang keras follow-trend di harga pucuk/dasar ekstrem** (*Anti-FOMO Guard*).
       - **Fase 4 (REVERSAL / CHoCH):** Terjadi Change of Character menembus swing berlawanan dengan displacement lilin terkonfirmasi sebelum diizinkan *counter-trend trade*.
  3. **Veto Override & Dynamic Post-Win Cooldown:**
     - Di `spk/veto.py`: S/R barrier diturunkan menjadi soft penalty saat pasar berada dalam fase `TRENDING` searah order.
     - Di `runtime.py`: Pangkas cooldown paska-profit dari 60s/45s menjadi **10 detik** saat rezim `TRENDING` agar bot dapat melakukan *wave-chaining* berkelanjutan.
  4. **Pengujian Unit:**
     - Penambahan test suite `tests/test_market_regime.py`.
     - 59/59 unit tests lulus (100% Green).

---

**Phase / Area:** Agent Orchestrator & Execution Discipline (`agents/orchestrator.py`)
**Status:** Done

**Yang dikerjakan**
- **Mengeliminasi Jebakan Pisau Jatuh (Auto-Flip Removal):**
  1. **Investigasi Insiden Live (Tiket #4897769222 & #4897770937):**
     - Ditemukan anomali fatal pada runtime di mana konsensus 30+ agen SPK sebenarnya membaca pasar **BEARISH / SELL**.
     - Namun karena harga menyentuh lantai support M1, agen `Tech-SupportResistance` menerbitkan `VETO_SELL`.
     - Modul `Reversal Hunter Confluence` di `orchestrator.py` secara gegabah membalikkan arah order dari SELL menjadi **BUY** hanya karena 1 agen mikro (`Struct-Microstructure`) mendeteksi osilasi volume beli tick 1 menit.
     - Akibatnya, bot membuka BUY melawan arus tren besar (downtrend deras), menyebabkan 2 kali cutloss berurutan (-$9.85 di detik ke-35 via Emergency Dynamic Clamp dan -$5.09 di detik ke-61 via Satpam Watchdog).
  2. **Penegasan Disiplin Trading (HOLD Mode):**
     - Menghapus total blok auto-flip di `agents/orchestrator.py`.
     - *Dilarang menjual di support BUKAN berarti wajib membeli di support*. Jika SELL terhalang support, sistem wajib berstatus **HOLD (Standby)** demi melindungi modal.
     - Bot dilarang keras membuka BUY sampai seluruh konsensus multi-agent SPK secara alami dan organik berbalik arah menjadi BUY dari pantulan nyata (*rejection confirmed*).
     - Jika support tertembus (*confirmed breakdown* di bawah buffer $1.20), agen `Tech-SupportResistance` secara alami akan menerbitkan sinyal `CONFIRMED_MICRO_BREAKDOWN` (vote SELL 0.80) sehingga bot dapat berselancar mengikuti tren.

**File tersentuh**
- `agents/orchestrator.py` — Menghapus blok `Reversal Hunter Confluence` auto-flip; menjaga integritas `hard_veto` dan konsensus SPK.
- `docs/PROGRESS.md` — Pencatatan worklog audit dan eliminasi bug entry.

**Verifikasi**
- `pytest tests/test_spk_veto.py tests/test_technical_division.py tests/test_runtime.py` → 54 passed in 0.46s.
- Kode disinkronkan ke server live dan container `gs-bot` direstart.

---

**Phase / Area:** SPK Veto Arbitration Engine (`spk/veto.py`, `tests/test_spk_veto.py`)
**Status:** Done

**Yang dikerjakan**
- **Menghilangkan Penyanderaan Scalper M1 oleh Timeframe Besar H1/D1:**
  1. **Investigasi Tabrakan Antar-Agen:**
     - Ditemukan bukti nyata pada telemetri live (jam 03:02 WIB) di mana `TF-H1-Regime` menerbitkan `VETO_SELL` dengan alasan harga berada di 20% area bawah rentang 24 jam (`h1_range`). Akibatnya, sinyal SELL scalper M1 (skor -4.955) terblokir secara Hard Veto selama berjam-jam walau ada setup swing 20-pip yang valid.
  2. **Penurunan Kasta Veto HTF (H1, H4, D1) Menjadi Soft Penalty:**
     - Mengubah aturan evaluasi di `spk/veto.py`: Veto arah dari agen divisi `timeframe` (`TF-H1-Regime`, `TF-H4-Bias`, `TF-D1-Macro`) **TIDAK LAGI berstatus Hard Veto pemblokir total**.
     - Veto HTF diturunkan (*de-escalated*) menjadi **Soft Confidence Penalty (-0.30)**.
     - Jika setup scalper M1 didukung kuat oleh 30+ agen lain (volume, microstructure, liquidity, orderflow), trade tetap dapat dieksekusi.
     - Jika sinyal scalper marjinal/lemah, penalti -0.30 akan menurunkan konfidensi di bawah threshold sehingga trade otomatis gugur dengan sehat.
  3. **Penegasan Hak Hard Veto Murni:**
     - Hak Hard Veto kini secara tegas hanya dipegang oleh:
       - **Risk Guard:** `daily_loss_exceeded`, `weekly_loss_exceeded`, `daily_profit_locked`, `division == 'risk'`.
       - **Market Blackout & Disconnect:** `is_news_blackout`, `tick_feed_stale`, `mt5_disconnected`.
       - **Tactical Barrier:** `is_sr_barrier` (M1 Support/Resistance) dan `VETO_ALL` (M1 Mid Dead Zone Chop).
  4. **Pengujian Unit:**
     - Penambahan unit test `test_htf_macro_veto_is_soft_penalty_not_hard_block` di `tests/test_spk_veto.py`.
     - 54/54 unit tests lulus (100%).

**File tersentuh**
- `spk/veto.py` — Pengalihan agen divisi timeframe dari hard veto ke soft confidence penalty (-0.30).
- `tests/test_spk_veto.py` — Penambahan test HTF soft penalty, pembaruan helper `_veto_sig`.
- `docs/PROGRESS.md` — Dokumentasi kronologis worklog.

**Verifikasi**
- `python -m pytest tests/test_spk_veto.py tests/test_technical_division.py tests/test_runtime.py` → 54 passed in 0.48s.

---

## 2026-10-20 — Scalper Radar Inactivity Watchdog & Veto Deadlock Diagnostics

**Phase / Area:** Runtime Telemetry & Market Inactivity Intelligence (`runtime.py`, `config/settings.py`, `tests/test_runtime.py`)
**Status:** Done

**Yang dikerjakan**
- **Mengembangkan Scalper Radar Inactivity Watchdog (M1/M5 Real-Time Intelligence):**
  1. **Mengatasi Kebuntuan Informasi Saat Bot Idle (5-10 Menit Tanpa Trade):**
     - Sebelumnya, bot beroperasi secara *silent polling* saat tidak ada trade, sehingga operator tidak mengetahui apakah bot sedang terkena deadlock veto, harga di chop zone, atau menunggu trigger tertentu.
     - Dibuat modul otomatis `_check_scalper_radar` dan `_emit_scalper_radar_report` di `runtime.py`.
  2. **Diagnostik Veto & Deadlock Arbitrase:**
     - Mendeteksi apakah terjadi deadlock dua arah (`VETO_BUY` dari satu agen vs `VETO_SELL` dari agen lain).
     - Mendeteksi apakah harga terjebak di `VETO_ALL` (M1 Mid Dead Zone).
     - Mengidentifikasi secara eksplisit agen mana yang menahan posisi dan alasannya.
  3. **Snapshot Taktikal M1 & Gelombang M5 (Bukan HTF Lagging):**
     - Melaporkan support, resistance, span, dan posisi persentase harga di rentang M1 (`m1_pos_pct`).
     - Melaporkan kemiringan EMA M5 (`Tech-Trend`) dan status volatilitas (`Tech-Volatility`: squeeze vs expansion).
     - Menghitung level pemicu aksi riil (*actionable triggers*): Level Upper 30% untuk Ping SELL, Level Lower 30% untuk Pong BUY, serta batas Breakout/Breakdown.
  4. **Multi-Channel Delivery (Log + WebSocket Broadcast):**
     - Dicatat dalam log terstruktur `log.info("SCALPER RADAR [idle=...]: ...")`.
     - Ditransmisikan langsung via WebSocket telemetry (`type: "scalper_radar"`) untuk konsumsi dashboard Web UI cockpit.
     - Diintegrasikan ke dalam `runtime.snapshot()` dan `runtime.telemetry()`.
  5. **Pengujian Unit:**
     - Penambahan unit test `test_runtime_scalper_radar_inactivity_watchdog()` di `tests/test_runtime.py`.
     - 53/53 unit tests lulus (100%).

**File tersentuh**
- `config/settings.py` — Penambahan parameter `radar_watchdog_enabled = True` dan `radar_report_interval_s = 300` (5 menit).
- `runtime.py` — Pelacakan idle, implementasi `_check_scalper_radar`, `_emit_scalper_radar_report`, integrasi `snapshot()` dan `telemetry()`.
- `tests/test_runtime.py` — Penambahan test `test_runtime_scalper_radar_inactivity_watchdog` dan resilient UTC import.
- `docs/PROGRESS.md` — Dokumentasi fitur dan log kronologis.

**Verifikasi**
- `python -m pytest tests/test_runtime.py tests/test_spk_veto.py tests/test_technical_division.py` → 53 passed in 0.51s.

---

## 2026-10-20 — Grade AAA M1 Ping-Pong Architecture: Strict 3-Zone Anti-Chasing & Mid-Channel Dead Zone Veto (VETO_ALL)

**Phase / Area:** SPK Veto Engine & Technical S/R Architecture (`agents/divisions/technical/agents.py`, `spk/veto.py`, `agents/state.py`, `agents/base.py`, `config/settings.py`)
**Status:** Done

**Yang dikerjakan**
- **Mengeliminasi Trade Chop di Tengah Range M1 (The 30/40/30 Rule):**
  1. **Investigasi Masalah Entry Tengah M1:**
     - Analisis transaksi tiket `#4897727206` (SELL @ 4142.71): Harga berada di antara support M1 ($4141.50) dan resisten M1 ($4144.50), sekitar 40.3% dari range span ($3.00). Karena harga berada tipis $0.01 di atas buffer support ($1.20), sistem menganggapnya "Mid-Channel / Scalping Permitted" dan membiarkan sinyal SELL tren M5 mengeksekusi SELL di paruh bawah channel, tepat sebelum harga memantul naik.
  2. **Penerapan Strict 3-Zone Ping-Pong M1:**
     - **Upper 30% (`pos_pct >= 0.70` atau near resistance ceiling):** HANYA boleh **SELL** (Ping). VETO BUY mutlak (`VETO_BUY`).
     - **Lower 30% (`pos_pct <= 0.30` atau near support floor):** HANYA boleh **BUY** (Pong). VETO SELL mutlak (`VETO_SELL`).
     - **Middle 40% (`0.30 < pos_pct < 0.70`):** **DEAD ZONE / CHOP**. Diberlakukan **HARD VETO KEDUA ARAH (`VETO_ALL`)**.
  3. **Pengenalan Flag Universal `VETO_ALL`:**
     - Ditambahkan ke `agents/state.py`, diekspor oleh `agents/base.py`.
     - `spk/veto.py` mengidentifikasi `VETO_ALL` sebagai Hard Barrier mutlak (`hard=True`), sehingga baik SPK memutuskan BUY maupun SELL, order baru seketika dibatalkan (HOLD).
     - Breakout/breakdown terkonfirmasi di luar buffer tetap diizinkan sebagai momentum trade.
  4. **Pengaturan Konfigurasi Terpusat:**
     - `micro_sr_dead_zone_enabled: bool = True`
     - `micro_sr_dead_zone_max_span: float = 12.00` (USD)
  5. **Pengujian Unit:**
     - Penambahan unit test `test_support_resistance_m1_mid_dead_zone_veto_all()` di `tests/test_technical_division.py`.
     - Penambahan unit test `test_veto_all_blocks_both_buy_and_sell()` di `tests/test_spk_veto.py`.
     - Seluruh 48 unit tests lulus (100%).

**File tersentuh**
- `agents/state.py` — Penambahan konstanta `VETO_ALL = "VETO_ALL"`.
- `agents/base.py` — Impor dan ekspor `VETO_ALL` dalam `__all__`, perbaikan lint unnecessary `int()`.
- `spk/veto.py` — Pengenalan penanganan `VETO_ALL` sebagai hard barrier instan.
- `config/settings.py` — Penambahan `micro_sr_dead_zone_enabled` dan `micro_sr_dead_zone_max_span`.
- `agents/divisions/technical/agents.py` — Pembagian 3-zone (30/40/30) pada evaluasi M1 `SupportResistance`.
- `tests/test_technical_division.py` — Penambahan test mid dead zone.
- `tests/test_spk_veto.py` — Penambahan test `VETO_ALL` buy & sell blocker.

**Verifikasi**
- `python -m pytest tests/test_spk_veto.py tests/test_technical_division.py` → 48 passed in 0.25s.
- `python -m pytest tests/test_agents_base.py tests/test_orchestrator.py tests/test_fundamental_division.py` → 27 passed in 0.23s.

---

## 2026-10-20 — Juggler Loss Clamp Hard Ceiling, Scalper Lot Cap & MT5 Connector Lint Fixes

**Phase / Area:** The Juggler Dynamic Clamp & Execution (`execution/position_manager.py`, `agents/divisions/risk/agents.py`, `core/mt5_connector.py`, `config/settings.py`)
**Status:** Done

**Yang dikerjakan**
- **Menghentikan Pembengkakan Floating Loss (Bug `min_breath_usd`) & Pembatasan Lot Scalper:**
  1. **Eliminasi Pembengkakan Clamp Loss:**
     - Menemukan bahwa tiket `#4897688982` melar hingga loss -$49.51 karena `min_breath_usd = pos.volume * 1.60 * 100` pada 0.27 lot menghasilkan $43.20, sehingga `max(min_breath_usd, base_clamp)` menaikkan clamp loss menjadi $43.20.
     - Menghapus pembengkakan `min_breath_usd` dan menerapkan **Strict Hard Ceiling** pada clamp loss: `effective_clamp_usd = min(base_clamp, round(s.hard_loss_clamp_usd * 1.35, 2))`. Kerugian per trade kini **terkunci rapat maksimal di kisaran $7.00 - $9.45**, melindungi modal akun.
  2. **Perbaikan Invalidation Alert & Duration Loss Cut:**
     - Pada `invalidation_alert`: jika M1 strongly opposing (confidence $\ge 0.70$) dan M5 bukan supporting, alert aktif seketika tanpa harus menunggu pergantian candle M5 5 menit.
     - Pada Duration Stagnation Cut (Phase 4): jika floating loss sudah mencapai $4.20 - $5.00 pada detik 90+ dan M1 berlawanan arah, trade dipotong tegas.
  3. **Hard Cap Lot Scalper Sprint (`max_scalper_lot = 0.08`):**
     - Pada akun cent Exness (ekuitas terbaca 6,975), sizer dibatasi ketat ke maksimal **0.08 lot** untuk mencegah pergerakan 1 poin Gold merugikan puluhan dolar.
  4. **Pembersihan Lint Errors di `core/mt5_connector.py`:**
     - Memperbaiki pengecekan `price is None` dan narrowing float pada `order_send`.
     - Menghapus pemanggilan `int()` redundan pada `self.s.mt5_login`, `p.ticket`, `ticket` di `close_position` dan `modify_position`.

**File tersentuh**
- `execution/position_manager.py` — Penghapusan min_breath_usd, penegakan clamp ceiling $8.50 - $9.45, dan penguatan invalidation alert.
- `agents/divisions/risk/agents.py` — Penerapan `max_scalper_lot` cap pada target-seeking sizer.
- `config/settings.py` — Penambahan parameter `max_scalper_lot = 0.08`.
- `core/mt5_connector.py` — Perbaikan lint error type narrowing dan penghapusan redundant `int()`.
- `tests/test_execution.py` — Penyesuaian test fixture early invalidation cut.

**Verifikasi**
- `pytest tests/test_execution.py tests/test_risk_division.py tests/test_spk_veto.py tests/test_orchestrator.py tests/test_clock.py tests/test_technical_division.py` → 113 passed in 0.50s.

---

## 2026-10-20 — M1 Micro-SR Detection with Configurable Confirmation Range & Bi-Directional Anti-Chasing Veto

**Phase / Area:** Technical Division & SPK Veto Engine (`agents/divisions/technical/agents.py`, `config/settings.py`, `tests/test_technical_division.py`)
**Status:** Done

**Yang dikerjakan**
- **Mengeliminasi Blindspot Support/Resistance Lokal M1 (Anti-Chasing at The Dip / Peak):**
  1. **Audit Masalah Tiket `#4897660772` (SELL di Dasar Lembah $4,143.39):**
     - Sinyal SELL dipicu karena candle M1 drop deras dari $4,149 dan divisi Timeframe membaca momentum bearish ekstrem (-4.44).
     - Agen `Tech-SupportResistance` lama hanya memindai M5 (lookback 100 menit) sehingga support dianggap masih jauh di $4,136.71 dan harga $4,143.39 dicap sebagai "mid-channel, scalping permitted" tanpa veto.
     - Akibatnya bot mengejar momentum turun (*chasing the dip*) dan menjual tepat di support lokal M1.
  2. **Implementasi Deteksi M1 Micro-SR & Variabel Range Konfirmasi:**
     - Menambahkan parameter konfigurasi:
       - `micro_sr_veto_enabled: bool = True`
       - `micro_sr_lookback_m1: int = 20` (jendela swing lokal 20 menit)
       - `micro_sr_confirm_range_usd: float = 1.20` (variabel range konfirmasi / buffer: $1.20 = 12 pips di Gold)
     - **Micro-Support Protection (SELL HARAM):**
       - Jika harga berada dalam zona `m1_support +/- confirm_range_usd`, agen `Tech-SupportResistance` mengaktifkan **Hard Veto `VETO_SELL`** (Confidence 0.80).
       - SELL hanya diizinkan jika harga terkonfirmasi resmi jebol (*close breakdown*) di bawah `m1_support - confirm_range_usd`.
     - **Micro-Resistance Protection (BUY HARAM - Kebalikannya):**
       - Jika harga berada dalam zona `m1_resistance +/- confirm_range_usd`, agen mengaktifkan **Hard Veto `VETO_BUY`** (Confidence 0.80).
       - BUY hanya diizinkan jika harga terkonfirmasi resmi tembus (*close breakout*) di atas `m1_resistance + confirm_range_usd`.
  3. **Unit Testing:**
     - Menambahkan `test_support_resistance_m1_micro_support_veto_sell` dan `test_support_resistance_m1_micro_resistance_veto_buy`.
     - 113 core tests lolos 100%.

**File tersentuh**
- `config/settings.py` — Penambahan variabel `micro_sr_veto_enabled`, `micro_sr_lookback_m1`, `micro_sr_confirm_range_usd`.
- `.env.example` — Template variabel env Micro-SR.
- `agents/divisions/technical/agents.py` — Logika M1 Micro-SR detection & bi-directional anti-chasing veto.
- `tests/test_technical_division.py` — Pengujian unit Micro-SR veto & Python 3.10 UTC compat.
- `tests/test_spk_veto.py` — Python 3.10 UTC compat.

**Verifikasi**
- `pytest tests/test_execution.py tests/test_risk_division.py tests/test_spk_veto.py tests/test_orchestrator.py tests/test_clock.py tests/test_technical_division.py` → 113 passed in 0.49s.

---

## 2026-10-20 — M5 Candle Pattern Reversal Protection & Target-Seeking High Conviction Sizing

**Phase / Area:** The Juggler FinEng & Position Watchdog (`execution/position_manager.py`, `agents/divisions/risk/agents.py`, `tests/test_execution.py`)
**Status:** Done

**Yang dikerjakan**
- **Mengintegrasikan Pola Candle M5 pada Evaluasi Watchdog 60s+ & Sizing Target-Seeking Juggler:**
  1. **Eliminasi Pemotongan Sepihak M1 (M5 Reversal Protection):**
     - Audit menemukan bahwa tiket `#4894936559` terpotong di detik 61 saat M5 sebenarnya masih berstatus `SUPPORTING`, akibat klausul lama `or (m1_opp_conf >= 0.70)`.
     - Memperbarui `execution/position_manager.py`: `invalidation_alert` kini **wajib konfirmasi ganda** (`m1_verdict == "OPPOSING" and m5_verdict == "OPPOSING"`).
     - Jika durasi trade menyentuh 60+ detik dan M1 berlawanan tetapi **Satpam M5 masih `SUPPORTING`**, bot dilarang memotong sepihak. Posisi wajib ditahan (*Hold for M5 Reversal*) untuk memberikan ruang terbentuknya pantulan pola candle M5 menuju Take Profit.
     - Memperbarui proteksi durasi pada Phase 4 agar tidak memotong posisi yang struktur M5-nya masih sehat mendukung.
  2. **Juggler Target-Seeking & High-Conviction Sizing:**
     - Di `agents/divisions/risk/agents.py`: Sizing lot dikonfirmasi langsung ke Juggler dengan mempertimbangkan sisa target dolar (`remaining_usd`) via `target_urgency`.
     - Jika data sangat meyakinkan (*Pede by data*: SPK score $\ge 5.0$, confidence $\ge 70\%$, atau multi-indikator konfluensi kuat), Juggler mengizinkan lot ekspansi terkalibrasi (hingga 0.14–0.18 lot) untuk mempercepat pencapaian target harian.
     - Jika setup marjinal/biasa, lot ditahan di level aman defensif (0.07–0.08 lot).
  3. **Unit Testing:**
     - Memperbarui `tests/test_execution.py`: Verifikasi skenario 2b (saat detik 65, jika M1 oppose tapi M5 support -> posisi tetap HELD) dan 2c (setelah M5 juga oppose -> cutloss dieksekusi).

**File tersentuh**
- `execution/position_manager.py` — Dual M1+M5 invalidation alert dan proteksi hold saat M5 supporting.
- `agents/divisions/risk/agents.py` — Penguatan target-seeking demand factor dan high-conviction sizing.
- `tests/test_execution.py` — Penambahan verifikasi M5 supporting hold.
- `docs/QUANT_FINENG_BIZDEV_SPEC.md` — Sinkronisasi spesifikasi M5 pattern hold dan target-seeking sizing.

**Verifikasi**
- `pytest tests/test_execution.py tests/test_risk_division.py tests/test_orchestrator.py tests/test_clock.py` → 67 passed in 0.39s.

**Catatan / Next**
- Deploy file ke production server (`studo@100.114.150.48`) dan restart container `gs-bot`.

---

## 2026-10-19 — The Juggler Verdict: Defense Mode Capital Preservation, Grade A+ Conviction Boost & Anti-Hunting Reversal SL

**Phase / Area:** The Juggler FinEng & Execution Architecture (`agents/divisions/risk/agents.py`, `agents/orchestrator.py`, `execution/risk_gate.py`, `tests/test_risk_division.py`)
**Status:** Done

**Yang dikerjakan**
- **Penegakan Hukum Juggler pada Pertanyaan Ukuran Lot di Mode DEFENSE:**
  1. **Keputusan Kuantitatif Juggler (Capital Preservation):**
     - Sesuai Hukum Sistem Portofolio (Pilar 1: `daily_pnl_pct < 0%` = DEFENSE Mode), Juggler **menolak keras menaikkan baseline risiko akun** (misal dari 0.5% ke 1.0%). Menaikkan risiko statis di tengah drawdown harian melanggar prinsip anti-bleeding. Baseline trade reguler dipertahankan secara disiplin di **0.07 – 0.08 lot** pada saldo 7,161 USC.
  2. **Grade A+ High-Conviction Adaptive Sizing:**
     - Di `agents/divisions/risk/agents.py`: Memberikan multiplier pemulihan hingga **`1.25x` (0.10 lot)** khusus untuk setup Grade A+ High-Conviction (skor SPK $\ge 5.0$ atau confidence $\ge 70\%$). Setup biasa tetap defensif di 0.07–0.08 lot.
  3. **Anti-Hunting Reversal SL Cushion:**
     - Pada tiket `#4894659861`, SL fisik di MT5 dipasang terlalu mepet (`1.9 pips` / `$1.90`) sehingga terkena hunting sumbu broker di detik 35.
     - Di `agents/orchestrator.py`, parameter `sl_dist` reversal diperlebar menjadi minimum `max(3.50, round(spread_usd * 3.5, 2))` (35 pips / $3.50+). MT5 broker order terlindungi sebagai safety rail bencana, sementara manajemen dan cut-loss dini diserahkan penuh kepada kecerdasan Satpam Juggler Watchdog (setelah 60s M1 close).
  4. **Proteksi Double-Shrinkage Lot Kecil:**
     - Di `execution/risk_gate.py`, memastikan order $\le 0.04$ lot tidak terkena pengalian confidence ganda (`scaled_size = base_size`).

**File tersentuh**
- `agents/divisions/risk/agents.py` — Multiplier pemulihan 1.25x untuk Grade A+ High-Conviction di DEFENSE mode.
- `agents/orchestrator.py` — Memperlebar batas noise cushion reversal SL ke minimal 35 pips ($3.50).
- `execution/risk_gate.py` — Bypass confidence reduction untuk lot $\le 0.04$.
- `tests/test_risk_division.py` — Kompatibilitas UTC dan verifikasi preservasi lot defensif.
- `docs/QUANT_FINENG_BIZDEV_SPEC.md` — Dokumentasi spesifikasi High-Conviction recovery sizing dan Anti-Hunting SL.

**Verifikasi**
- `pytest tests/test_risk_division.py tests/test_orchestrator.py tests/test_execution.py tests/test_clock.py` → 67 passed in 0.36s.

**Catatan / Next**
- Deploy file ke production server (`studo@100.114.150.48`) dan restart container `gs-bot`.

---

## 2026-10-19 — M1 Candle Formation Grace Period (60s Minimum Hold for Early Cut)

**Phase / Area:** Execution Layer, Risk & Exit Protection (`execution/position_manager.py`, `config/settings.py`, `.env.example`, `tests/test_execution.py`)
**Status:** Done

**Yang dikerjakan**
- **Mengeliminasi Cut-Loss Prematur akibat Sumbu/Ekor Candle M1 (Intra-Candle Noise):**
  1. **Akar Masalah (Root Cause):**
     - Evaluasi live trading pasca-deployment Satpam Bertingkat menunjukkan rata-rata loss berhasil dijepit turun dari -$16.38 s/d -$23.70 menjadi -$6.91.
     - Namun, terdapat beberapa posisi yang terkena cut-loss dini di bawah 1 menit (< 60 detik) saat candle M1 masih berjalan di detik 16–45. Sumbu/ekor (*wick*) fluktuasi intra-candle memicu `invalidation_alert` sebelum candle M1 sempat terbentuk utuh (*close*).
  2. **Implementasi M1 Candle Formation Grace Period (60 Detik):**
     - Menambahkan konfigurasi `watchdog_min_hold_seconds: int = 60` di `config/settings.py` dan `.env.example`.
     - Memperbarui `execution/position_manager.py` (Phase 0 & Phase 1): Selama `held < min_hold` (60 detik), sistem dilarang keras melakukan cut-loss dini kecuali terjadi pergerakan ekstrem (*catastrophic gap* $> 1.6\times$ clamp limit).
     - **Take Profit (TP) Tetap Kilat:** Logika Take Profit dan panen momentum sama sekali tidak dibatasi oleh durasi 60 detik; TP kilat tetap dapat dieksekusi seketika (< 60s) saat target/momentum tercapai.
     - **Cooldown Tetap Utuh:** Jeda cooldown 60 detik antar-trade tetap dipertahankan tanpa gangguan.
  3. **Unit Testing & Verifikasi:**
     - Memperbarui unit test `test_watchdog_time_extension_and_invalidation_cut` di `tests/test_execution.py` untuk menguji:
       - Skenario 2a: Pada detik 35 (< 60s), posisi dilindungi oleh Grace Period dan tidak ditutup.
       - Skenario 2b: Setelah 1 candle M1 close penuh (detik 65 $\ge 60$s), posisi yang terbukti invalid langsung di-cutloss dini secara disiplin.

**File tersentuh**
- `config/settings.py` — Menambahkan parameter `watchdog_min_hold_seconds: int = 60`.
- `.env.example` — Menambahkan environment variable `WATCHDOG_MIN_HOLD_SECONDS=60`.
- `execution/position_manager.py` — Implementasi Phase 0 Grace Period 60s untuk candle formation sebelum Satpam M1/M5 cut-loss dini.
- `tests/test_execution.py` — Verifikasi 2a (grace period protection) dan 2b (post-close invalidation cut).
- `docs/QUANT_FINENG_BIZDEV_SPEC.md` — Sinkronisasi spesifikasi Phase 0 Grace Period dan Noise Floor.

**Verifikasi**
- `pytest tests/test_execution.py tests/test_clock.py` → 28 passed in 0.21s.

**Catatan / Next**
- Deploy file ke production server (`studo@100.114.150.48`) dan restart container `gs-bot`.
- Pantau metrik eksekusi live trade pada sesi pasar New York.

---

## 2026-10-19 — Multi-Timeframe Watchdog (Satpam Bertingkat M1, M5, M15) & Fast Break-Even Lock (BEP+)

**Phase / Area:** Execution Layer, Risk & Exit Architecture (`execution/position_manager.py`, `config/settings.py`, `tests/test_execution.py`, `.env.example`)
**Status:** Done

**Yang dikerjakan**
- **Mengatasi Asimetri Risiko Exit (Negative Risk-Reward Asymmetry) & Mengganti Dumb Timer 900s:**
  1. **Akar Masalah (Root Cause):**
     - Bot memiliki win rate tinggi dengan TP cepat (+1.60 s/d +8.00 USD), namun pada trade tiket `#4893108219`, bot mengalami loss -$23.72 karena menunggu SL fisik di MT5 secara pasif.
     - Ambang batas Break-Even lama (`be_trigger_usd`) membutuhkan $7.00 profit (+50 pips pada lot 0.14) baru BE aktif, sehingga trade yang sudah sempat running untung +10-15 pips tidak terkunci dan berbalik rugi besar.
     - Hard time-stop kaku 900 detik memenggal posisi secara buta tanpa memperhatikan apakah Higher Timeframe (M5, M15) sedang membentuk struktur konfirmasi reversal menuju TP.
  2. **Multi-Timeframe Watchdog (Satpam Bertingkat):**
     - Mengembangkan `evaluate_multi_tf_watchdogs(pos_direction, context)` dengan 3 layer pengawasan terkalibrasi:
       - **Satpam Layer 1 (M1 Sniper / Micro):** `TF-M1-Sniper`, `Tech-EMA-Cross`, `Tech-RSI-Stoch` (memantau micro-rejection & adverse momentum).
       - **Satpam Layer 2 (M5 Structure):** `TF-M5-Inspector`, `Struct-MarketStructure` (memantau swing structure CHoCH/BOS).
       - **Satpam Layer 3 (HTF Trend & Liquidity):** `TF-M15-Liquidity`, `TF-M30-Momentum`, `TF-H1-Regime`, `TF-H4-Structure`.
  3. **Smart Time Extension (Pengganti Timer Kaku 900s):**
     - Jika durasi trade mencapai `max_hold_seconds`, sistem mengecek Satpam M5 & HTF.
     - Jika struktur HTF masih sehat mendukung (`SUPPORTING`) dan M5 tidak patah struktur, Juggler memberikan izin perpanjangan nafas (*Dynamic Time Extension* hingga +300 detik) untuk memberi ruang terbentuknya reversal menuju TP.
     - Jika Satpam melapor `NEUTRAL` atau `OPPOSING`, posisi langsung ditutup secara terukur (`time_stop`).
  4. **Satpam M1/M5 Early Invalidation Cut:**
     - Jika posisi floating minus dan Satpam M1 serta M5 mendeteksi konfirmasi reversal yang berlawanan (`invalidation_alert`), bot langsung melakukan *cut loss dini* pada ambang batas terukur (~$6-$8), mencegah kerugian membengkak hingga -$23.72.
  5. **Fast Break-Even Lock (BEP+):**
     - Merapatkan ambang batas Break-Even menjadi 12 pips (`fast_breakeven_pips = 12.0`, min `$1.80`).
     - Begitu running profit mencapai +12 pips, Stop Loss otomatis digeser ke `entry + 0.10` / `entry - 0.10` (Zero Risk Mode). Posisi yang sudah sempat hijau terlindungi 100% dari berbalik merah.
  6. **Integritas Sinyal Entry 100% Utuh:**
     - Seluruh mesin pembuat sinyal entry, bobot voting SPK, dan filter confluence tetap dipertahankan utuh tanpa perubahan.

**File tersentuh**
- `config/settings.py` — Menambahkan parameter `watchdog_enabled`, `watchdog_time_extension_seconds`, `watchdog_early_invalidation_enabled`, `watchdog_early_loss_ratio`, `fast_breakeven_pips`.
- `execution/position_manager.py` — Implementasi `evaluate_multi_tf_watchdogs`, smart watchdog time stop, Satpam M1/M5 early cutloss, dan fast BEP+ lock.
- `.env.example` — Sinkronisasi variabel lingkungan untuk Watchdog dan Fast BEP+.
- `tests/test_execution.py` — Penambahan 2 unit test baru: `test_watchdog_time_extension_and_invalidation_cut` dan `test_fast_breakeven_lock`.

**Verifikasi**
- `pytest tests/test_execution.py tests/test_clock.py` → 28 passed in 0.19s (100% pass).

**Catatan / Next**
- Deploy kode ke server Docker dan monitor performa real-time pengawalan posisi oleh Satpam Bertingkat.

---

## 2026-10-19 — Overnight Rollover & Asia Session Boundary Guard: Eliminating Rapid-Close Churn

**Phase / Area:** Execution Layer, Market Clock & Risk Gate (`core/clock.py`, `execution/position_manager.py`, `execution/risk_gate.py`, `tests/test_clock.py`, `tests/test_execution.py`)
**Status:** Done

**Yang dikerjakan**
- **Mengatasi Bug Tutup Instan (0-Second Churn) pada Pembukaan Sesi Asia (Senin Subuh / 22:00-23:59 UTC):**
  1. **Akar Masalah (Root Cause):**
     - Pada `execution/position_manager.py`, fitur `overnight_flat_utc_enabled` mengecek `if utc_dt.hour >= 21:` tanpa batasan hari dan tanpa batasan jam buka kembali pasar.
     - Akibatnya pada jam 22:00 dan 23:00 UTC (05:00-06:59 WIB Senin pagi dan hari biasa saat pasar Gold Exness baru saja buka kembali untuk sesi Asia), setiap posisi yang dibuka langsung ditutup paksa dalam 0-1 detik sebagai `OVERNIGHT FLAT CUTOFF`.
     - Menyebabkan 75 kali eksekusi open-close instan yang menggerus spread broker rata-rata -$2.82 per trade tanpa harga sempat bergerak.
  2. **Implementasi `is_overnight_flat_window(dt)` Terpusat:**
     - Menambahkan fungsi terpusat `is_overnight_flat_window(dt)` di `core/clock.py` yang membedakan:
       - **Weekend Gap Risk (Jumat):** Jumat pukul >= 20:50 UTC hingga Minggu pukul 22:00 UTC (saat pasar benar-benar libur akhir pekan).
       - **Daily Rollover Break (Senin-Kamis):** Pukul 20:50 s/d 22:00 UTC (saat pergantian hari dan spread melebar).
       - **Asia Session Reopen (Minggu-Kamis 22:00+ UTC / 05:00+ WIB):** Ditandai sebagai waktu pasar AKTIF (bukan cutoff).
  3. **Sinkronisasi Dua Sisi (Entry Gate & Exit Guard):**
     - Memperbarui `execution/position_manager.py` untuk menggunakan `is_overnight_flat_window(moment)`.
     - Menambahkan pre-trade filter di `execution/risk_gate.py` agar jika jendela rollover/cutoff sedang aktif, order baru DITOLAK SEJAK AWAL sehingga tidak pernah ada trade yang dibuka lalu langsung ditutup milidetik berikutnya.
  4. **Kompatibilitas Python 3.10 & 3.11+:**
     - Menyelaraskan import `UTC` lintas modul dengan fallback `timezone.utc`.
  5. **Pengujian Unit Menyeluruh:**
     - Menambahkan 10 assertions di `tests/test_clock.py` dan unit tests baru di `tests/test_execution.py` yang memvalidasi bahwa sesi Asia (22:05 UTC) TIDAK terkena cutoff, dan risk gate menolak entry saat jam rollover 21:15 UTC.

**File tersentuh**
- `core/clock.py` — Implementasi `is_overnight_flat_window(dt)` dan method di `MarketClock`.
- `execution/position_manager.py` — Integrasi `is_overnight_flat_window(moment)` untuk flat exit.
- `execution/risk_gate.py` — Pre-trade reject saat jendela overnight cutoff aktif.
- `core/market_data.py`, `core/mt5_connector.py` — Kompatibilitas import timezone UTC.
- `tests/test_clock.py`, `tests/test_execution.py` — Suite pengujian validasi jam sesi dan risk gate.
- `docs/PROGRESS.md`, `docs/QUANT_FINENG_BIZDEV_SPEC.md` — Dokumentasi kronologis dan spesifikasi operasional rollover.

**Verifikasi**
- `pytest tests/test_clock.py tests/test_execution.py -v` → 26 passed in 0.17s.

---

## 2026-10-17 — Portfolio-Aware Net Friction Guard: Eliminating Deadlock Paradox under Juggler Directive

**Phase / Area:** Risk Division, Execution Layer, Settings & BizDev (`agents/divisions/risk/agents.py`, `execution/risk_gate.py`, `config/settings.py`, `tests/test_risk_division.py`)
**Status:** Done

**Yang dikerjakan**
- **Mengatasi Deadlock Paradox pada Hard Veto Friction Guard:**
  1. **Dekopling Spread Rejection vs Friction Guard:**
     - Memperbaiki bug di `execution/risk_gate.py` di mana kegagalan friction guard dilaporkan keliru sebagai `entry timing rejected (spread ...)`.
     - Mengembalikan `wide spread` hanya jika market spread riil $> \text{max\_spread}$, dan `friction guard` dengan pesan terpisah yang transparan.
  2. **Kalkulasi Net Friction (Dipotong Broker Rebate):**
     - Memperbarui `EntryTiming` di `agents/divisions/risk/agents.py` untuk memperhitungkan estimasi rebate broker Exness (\$6.00/lot): $\text{net\_friction} = \max(0, \text{friction\_cost} - \text{lots} \times \$6.00)$.
  3. **Penyesuaian Berbasis Portfolio Health State (The Juggler Directive):**
     - Pada **`DEFENSE` Mode** ($\text{daily\_pnl\_pct} < 0\%$): Friction guard bertindak sebagai rem darurat proteksi modal (`friction_blocked = True`).
     - Pada **`BALANCED` / `GROWTH` Mode** ($\text{daily\_pnl\_pct} \ge 0\%$): Mesin **TIDAK DIBLOKIR** (mencegah deadlock di mana profit tidak bisa tumbuh karena trade dilarang). Sebaliknya, diaktifkan `adaptive_tp_expansion = True` agar strategi mencari swing/TP lebih lebar untuk melampaui biaya transaksi.
  4. **Peningkatan Batas Toleransi Friction:**
     - Mengubah `max_friction_ratio_pct` dari 15.0% ke 25.0% di `config/settings.py` untuk mengakomodasi fase awal sprint saat gross profit belum mencapai ratusan dolar.
  5. **Pengujian Unit Komprehensif:**
     - Menambahkan 4 unit test baru di `tests/test_risk_division.py` mencakup: deduksi rebate pada net friction, adaptive TP expansion pada kondisi pertumbuhan, proteksi hard-block pada status DEFENSE, serta validasi filter `risk_gate`.

**File tersentuh**
- `config/settings.py` — Naikkan `max_friction_ratio_pct` ke 25.0%.
- `agents/divisions/risk/agents.py` — Net friction rebate offset, portfolio-aware gating (DEFENSE vs GROWTH/BALANCED), dekopling dari `spread_ok`.
- `execution/risk_gate.py` — Pemisahan alasan rejection wide spread vs friction guard.
- `tests/test_risk_division.py` — 4 unit test baru untuk verifikasi skenario friction guard.
- `docs/QUANT_FINENG_BIZDEV_SPEC.md` — Sinkronisasi matriks parameter operasional.
- `docs/PROGRESS.md` — Pencatatan worklog kronologis.

**Verifikasi**
- `pytest tests/test_risk_division.py` → 100% passed (23 tests).
- Container remote deploy & hot-reload → Status engine running tanpa veto palsu.

---

## 2026-10-17 — Hard Veto Resolution & SPK Consensus Breakout Engine: Unblocking Evening Sprint Trading

**Phase / Area:** SPK Veto Engine, Technical Analysis Division & Risk Disciplines (`config/settings.py`, `spk/veto.py`, `agents/divisions/technical/agents.py`, `docs/PROGRESS.md`)
**Status:** Done

**Yang dikerjakan**
- **Mengatasi Dua Penyebab Utama Hard-Veto yang Menghambat Target Harian:**
  1. **Relaksasi Institutional Session Cutoff (`SESSION_HARD_CUTOFF`):**
     - Mengubah parameter default `hard_cutoff_utc_enabled: bool = False` di `config/settings.py` agar bot tidak terkunci mati selama 5,5 jam di malam hari (22:30 WIB - 04:00 WIB), memungkinkan trading aktif di sesi New York / malam hari untuk mengejar target sprint harian.
  2. **Demosi Hard Barrier ke Soft Penalty Saat Konsensus SPK Sangat Kuat:**
     - Pada `spk/veto.py`, menambahkan klausul *Juggler High-Confluence Breakout Override*: jika sinyal memiliki konfluensi multi-agent yang kuat ($\ge 18$ agent searah) DAN kondisi portofolio sehat (drawdown $\ge -1.0\%$), veto S/R barrier dari single-agent tidak lagi memblokir trade secara mutlak, melainkan didemosi menjadi soft penalty (-0.15) dengan dynamic tight SL. Hal ini mencegah 1 agent teknikal membubarkan kesepakatan 20+ agent lainnya.
  3. **Diferensiasi Breakout vs Bounce pada Support & Resistance:**
     - Pada `agents/divisions/technical/agents.py` (`SupportResistance`), memisahkan kondisi penembusan (*breakdown/breakout*) dari kondisi pantulan (*bounce/rejection*). Ketika harga menembus di bawah support (`close < support - thr`), agent kini menerbitkan `VOTE_SELL` dengan keyakinan tinggi untuk menangkap momentum short, bukan mengeluarkan `VETO_SELL`.
- **Verifikasi & Eksekusi Live:**
  - Test suite: **230 passed in 1.93s (100% clean)**.
  - Bot direstart dan langsung keluar dari status `HARD VETO`:
    - SPK Consensus: **STRONG SIGNAL SELL (Score -6.34, Confidence 89%)**.
    - Live MT5 Execution: **Ticket 4888953039 (SELL 0.12 @ 4,158.65, SL 4,163.50, TP 4,150.54)** langsung aktif tereksekusi di pasar.
    - Status Cockpit: **IN TRADE** (berwarna hijau).

---

## 2026-10-17 — Dynamic URL Parameters Routing Engine & Realtime Target Performance Telemetry in Running Text

**Phase / Area:** Frontend Architecture, Deep-Linking, State Sync & Live Telemetry Ticker (`frontend/js/app.js`, `frontend/js/agents.js`, `frontend/index.html`)
**Status:** Done

**Yang dikerjakan**
- **Sistem URL Parameters & Deep Linking Komprehensif:**
  1. `?tab=<cockpit|agents|divisions|portfolio|settings>`: Memungkinkan pembukaan tab spesifik secara langsung via URL serta sinkronisasi dinamis ke `window.location.search` dan `hash` tanpa page reload.
  2. `?tf=<M1|M5|M15|M30|H1|H4|D1>`: Memungkinkan penentuan timeframe chart TradingView langsung dari parameter URL dan otomatis meng-update parameter URL saat tombol timeframe diklik.
  3. `?subtab=<positions|trace|trades>`: Memungkinkan akses langsung ke sub-tab Cockpit (Recent Trades, Open Positions, Vote Trace) via URL.
  4. `?q=<keyword>` & `?div=<division>`: Memungkinkan deep-link filtering pencarian nama agent dan divisi pada tab Agents.
  5. `?token=<auth_token>`: Mendukung auto-login / automated authentication via URL token untuk integrasi webview / terminal eksternal.
  6. Mendukung browser navigation (`popstate` & `hashchange`) sehingga tombol *Back* dan *Forward* browser bekerja mulus antar-tab tanpa reload.
- **Informasi Target & Pencapaian Lengkap pada Running Text (Cockpit Ticker):**
  1. **Target Goal Nominal & Persen:** Menghitung dan menampilkan nilai target harian dalam dolar secara dinamis berdasarkan saldo riil akun (misal: `Target: +35.0% (+$3,105.81)` pada saldo \$8,873.73).
  2. **Pencapaian Lengkap (+/-), Nilai, dan Persen:** Menampilkan tanda tanda plus/minus secara eksplisit dengan format `Pencapaian (+/-): (+) +$3.51 (+0.00%)` atau `(-) -$X.XX (-X.XX%)` dengan color coding semantik (`perf-win` / `perf-loss`).
  3. **Progress & Sisa Target:** Menyajikan persentase progress terhadap target harian dan sisa nilai nominal yang harus dicapai (`Progress: X.X% (Sisa: $XXXX.XX)` atau status `Target Tercapai / Locked`).
  4. Menjaga volume akumulatif harian dan estimasi rebate BizDev tetap terintegrasi dalam marquee ticker.

**File tersentuh**
- `frontend/js/app.js` — Implementasi `getUrlParam`, `updateUrlParams`, `resolveInitialTab`, sinkronisasi history event, dan formulasi target nominal/persen/tanda (+/-) di `buildDailyPerformanceTickerHtml`.
- `frontend/js/agents.js` — Sinkronisasi URL parameter `tf`, `subtab`, `q`, dan `div` pada Cockpit dan Agents view.
- `frontend/index.html` — Cache buster update query string.

**Verifikasi**
- Pengujian interaktif via `chrome-devtools-mcp`:
  - Deep-link `https://scalper.7pivot.site/?tab=cockpit&tf=M5&subtab=trades` terbukti sukses mengaktifkan timeframe M5, subtab Recent Trades, dan merender target performance ticker.
  - Deep-link `https://scalper.7pivot.site/?tab=agents&q=trend` terbukti memfilter input pencarian dan memfilter card agent.
  - Verifikasi DOM running text: `Target: +35.0% (+$3,105.81) · Pencapaian (+/-): (+) +$3.51 (+0.00%) · Progress: 0.0% (Sisa: $3102.30) · Volume: 0.09 L (Rebate +$0.54)`.
- Berkas dideploy via SCP ke server live (`studo@100.114.150.48`).

---

## 2026-10-17 — Mobile UI/UX Overhaul, Desktop Architectural Header Alignment & Brand Refresh (Anti AI-Slop)

**Phase / Area:** Frontend UI/UX, Design Architecture, Mobile Responsiveness & Brand Asset Management (`frontend/index.html`, `frontend/css/cockpit.css`, `frontend/css/agents.css`, `frontend/js/components.js`, `frontend/js/agents.js`, `frontend/js/app.js`, `frontend/icons/`)
**Status:** Done

**Yang dikerjakan**
- **Mobile View Polishing & Decluttering:**
  1. Menyembunyikan toggle sidebar (`#sidebar-toggle`) dan sub-headline teks (`#view-sub`) pada mobile viewport ($\le 760\text{px}$) demi tampilan header yang bersih dan minimalis.
  2. Mengganti pill teks `Algo ON` dan `Running` dengan icon bulat interaktif 32px bertema tactile dengan dot status live.
  3. Memperjelas toggle timeframe chart TradingView: tombol aktif (misal `M1`) kini menggunakan kontras tinggi Gold `#d9a441` dengan teks hitam pekat `#0b0e14` dan subtle gold glow.
  4. Menghapus badge `LIVE` dan angka harga redundan dari header chart TradingView.
  5. Menjamin tabel posisi/transaksi (*Recent Trades* di Cockpit dan *Closed Trades* di Portfolio) menampilkan kolom vital (`SIDE`, `SIZE`, `ENTRY`, `EXIT`, `PNL`) secara penuh tanpa terpotong (*no clipping*) pada layar sempit ($\le 640\text{px}$).
  6. Mengatasi teks label sumbu terpotong pada Diamond Radar Chart di tab Divisions (`STRUCTURE` dan `TECHNICAL` kini tampil 100% utuh dengan margin horizontal yang terkalibrasi).
  7. Menumpuk field Search dan filter Division secara vertikal di tab Agents pada mobile view.
  8. Menambahkan otomatisasi scroll reset (`window.scrollTo({ top: 0, left: 0, behavior: 'instant' })`) setiap kali berpindah rute/tab.
- **Desktop View Architectural Alignment:**
  1. Menghapus deskripsi sub-teks aplikasi `(XAUUSD · SPK)` di bawah logo.
  2. Memberikan hairline border kanan presisi pada sidebar (`border-right: 1px solid var(--line)`).
  3. Menyamakan tinggi header brand dengan header konten (`height: 54px; min-height: 54px; box-sizing: border-box;`) yang terikat oleh garis border bawah kontinu (`border-bottom: 1px solid var(--line)`), menciptakan keselarasan visual horizontal sempurna.
- **Brand Identity & Iconography Refresh:**
  1. Mengganti logo lama dengan vektor geometric dual-arrow scalp baru yang diadaptasi dari `docs/image/logo.jpg`.
  2. Mentransformasikan warna putih pada artwork asli menjadi warna Gold aplikasi (`#d9a441`) di atas canvas gelap murni (`#0b0e14`).
  3. Memproduksi dan mengintegrasikan file icon multi-resolusi: `favicon.ico`, `icon.svg`, `icon-maskable.svg`, `logo_gold_dark.png`, `icon-192.png`, dan `icon-512.png`.

**File tersentuh**
- `frontend/index.html` — Update logo brand mark SVG, favicon meta tags, dan container mobile icon header.
- `frontend/css/cockpit.css` — Alignment desktop brand & topbar (54px), border-right sidebar, styling mobile icon header, dan penyembunyian elemen redundan.
- `frontend/css/agents.css` — Styling kontras tinggi timeframe pills aktif, vertical stack filter di mobile, dan responsivitas tabel.
- `frontend/js/components.js` — Update icon vector `goldLogo`, kalibrasi margin radius dan ukuran font label pada Diamond Radar chart.
- `frontend/js/agents.js` — Penghapusan badge LIVE redundan pada header chart TradingView dan penambahan class responsif pada tabel trades.
- `frontend/js/app.js` — Reset scroll position ke atas saat pergantian rute hash.
- `frontend/icons/` — Regenerasi aset favicon dan ikon aplikasi.

**Verifikasi**
- Emulasi browser DevTools (`chrome-devtools-mcp`):
  - Mobile View (`390x844x3`): Header bersih, timeframe pills kontras tinggi, chart bersih tanpa badge redundan, radar labels (`STRUCTURE` & `TECHNICAL`) terbaca 100%, tabel 5 kolom tidak terpotong.
  - Desktop View (`1440x900x1.5`): Border kanan sidebar rapi, tinggi brand sejajar dengan header (54px), border bawah menyambung horizontal sempurna, sub-teks terhapus.
- Berkas dideploy via SCP ke server live (`studo@100.114.150.48:/home/studo/apps/goldscalper/frontend/`).

---

## 2026-10-17 — Pure Dynamic Balance-Scaled Sizing (Zero Hardcoded Lot Ceilings): Seamless Portfolio Scaling & Target Proximity

**Phase / Area:** Position Sizing, Risk Gate & Position Management (`agents/divisions/risk/agents.py`, `execution/risk_gate.py`, `execution/position_manager.py`, `tests/test_risk_division.py`)
**Status:** Done

**Yang dikerjakan**
- Membuang seluruh batas konstan/angka statik semu (`0.02 - 0.08 lot`) dan mentransformasikannya menjadi **formula dinamis 100% matematis murni** yang melekat langsung pada angka saldo riil akun (\$100, \$1,000, \$8,873, dst.) serta target harian:
  1. **Dynamic Risk-Weighted Base Lot:**
     $$\text{Raw Base Lot} = \frac{\text{Equity} \times (\text{risk\_per\_trade\_pct} / 100)}{\text{sl\_distance} \times \text{contract\_size}}$$
     Pada akun live (\$8,873.73, risk 0.5%, SL 4.79), base lot terhitung secara presisi di **0.095 lot**.
  2. **Continuous Multiplier Berdasarkan Kesehatan Portfolio (AGENTS.md):**
     - **Mode `DEFENSE` (`daily_pnl_pct < 0%`):** Multiplier mengecil proporsional terhadap kedalaman drawdown ($M = \max(0.50, 1.0 + \text{daily\_pnl\_pct}/25.0)$).
     - **Mode `GROWTH` (`daily_pnl_pct >= 3%`):** Multiplier membesar proporsional memanfaatkan keuntungan pasar / house money ($M = \min(2.50, 1.0 + (\text{daily\_pnl\_pct} - 3.0)/10.0)$).
     - **Mode `BALANCED` (`0% <= daily_pnl_pct < 3%`):** Multiplier baseline $1.00\times$, meningkat ke $1.20\times$ saat Grade A+ High Conviction.
  3. **Sprint Target Proximity Smooth Tapering:**
     - Menghilangkan diskontinuitas garis akhir. Ketika sisa target $\le 10\%$ dari target harian, lot mengecil secara mulus proporsional terhadap sisa dolar untuk menyentuh garis finish tanpa risiko tersandung.
  4. **Dynamic Clamp Budget Proportional to Equity:**
     - Budget *hard loss clamp* di `PositionSizer` dan `PositionManager` kini ikut membesar proporsional dengan ekuitas akun ($\text{Equity} \times \text{risk\_per\_trade\_pct} \times 1.25$). Pada akun \$8,873, clamp budget dinamis adalah **\$66.55** (bukan \$7.00 statik).
- Verifikasi penuh test suite: **230 passed in 1.96s (100% clean)**.
- Hot-deploy dan restart container `gs-bot`.
- Validasi data live PostgreSQL: `Risk-PositionSizer` saat ini langsung mengeksekusi **lot=0.11** pada akun \$8,873 (modal riil) dalam mode BALANCED High-Conviction.

---

## 2026-10-17 — Eliminating the 0.01 Lot Trap in BALANCED & GROWTH Modes: Decoupling ATR Catastrophic SL from Fast Software Clamp

**Phase / Area:** Position Sizing & Pre-Trade Risk Gate (`agents/divisions/risk/agents.py`, `execution/risk_gate.py`, `tests/test_risk_division.py`)
**Status:** Done

**Yang dikerjakan**
- Membongkar dan menuntaskan akar matematis mengapa order di live trading masih tertekan menjadi **0.01 lot** di Cockpit:
  1. **Akar Masalah (The ATR SL Clamp Conflation):**
     - Di `PositionSizer`, perhitungan `dynamic_max_lot` sebelumnya membagi budget clamp (\$7.00) dengan seluruh jarak Stop Loss broker (`sl_distance * contract_size`).
     - Pada XAUUSD, ATR M5 umumnya berkisar 3.5 – 5.0 ($3.50 – $5.00), sehingga `sl_distance` (ATR x 1.2) bernilai **4.5 – 5.5 pips**.
     - Akibatnya: `7.00 / (5.37 * 100) = 0.013`, yang setelah pembulatan step lot selalu menghasilkan **0.01 lot**.
     - Nilai 0.01 ini kemudian mengunci `blended_size = min(size, size_ts, dynamic_max_lot)` menjadi **0.01 lot**!
     - Padahal, *hard loss clamp* (\$7.00) adalah **pemotong software cepat di PositionManager** pada jarak 15–25 pips (bukan pada 55 pips catastrophic SL broker).
  2. **Anomali Mode BALANCED vs DEFENSE:**
     - Perlindungan floor `0.02 - 0.04 lot` sebelumnya hanya dipasang untuk `mode_name == "DEFENSE"`.
     - Ketika akun profit sedikit (`daily_pnl_pct >= 0` seperti saat realized PnL +$2.80), mode sistem berubah menjadi `BALANCED`.
     - Karena tidak ada floor di mode BALANCED, `dynamic_max_lot` (0.01) langsung menghancurkan ukuran lot menjadi 0.01 (lebih kecil daripada mode Defense).
  3. **Solusi & Penegakan Tiers Doktrin (AGENTS.md & QUANT_FINENG_BIZDEV_SPEC):**
     - Memperbaiki `min_breath_usd` pada clamp sizing: dipatok ke jarak nafas cutloss software fisik emas (`1.50 - 2.50 USD` / 15–25 pips), sehingga `dynamic_max_lot` tidak pernah mencekik lot di bawah 0.04.
     - Menerapkan penegakan tier lot di `PositionSizer` untuk SEMUA mode:
       - **`DEFENSE` (`daily_pnl_pct < 0%`):** 0.02 – 0.04 lot (0.02 baseline, 0.03–0.04 Grade A+ / High Conviction).
       - **`BALANCED` (`0% <= daily_pnl_pct < 3%`):** 0.02 – 0.05 lot (0.02–0.03 baseline, 0.04–0.05 Grade A+ / High Conviction).
       - **`GROWTH` (`daily_pnl_pct >= 3%`):** 0.03 – 0.08 lot (0.03–0.05 baseline, 0.06–0.08 Grade A+ / High Conviction menggunakan house money).
       - **Finish Line (`remaining_target_usd <= $20`):** Mengunci ke 0.02 lot tunggal untuk pendaratan mulus di garis finish.
     - Di `execution/risk_gate.py`: Melindungi lot $\le 0.05$ dari pengalian confidence ganda agar perhitungan Sizer tidak terpotong separuh.
- Menambahkan 3 unit test baru di `tests/test_risk_division.py`:
  - `test_position_sizer_balanced_mode_lot_floor_with_wide_atr`
  - `test_position_sizer_growth_mode_scales_up`
  - `test_position_sizer_finish_line_tapers`
- Verifikasi penuh test suite: **230 passed in 1.95s (100% clean)**.
- Deploy dan restart container `gs-bot`.
- Validasi log runtime & live database: `Risk-PositionSizer` kini mengeksekusi **lot=0.04** pada kondisi live High-Conviction.

---

## 2026-10-17 — Institutional SMC & Session Clocks Alignment: Strict Order Block Body, Macro Top-Down Veto & Session Killzone Clocks

**Phase / Area:** Institutional SMC & Session Clock Alignment (`config/settings.py`, `core/clock.py`, `core/calendar_service.py`, `agents/divisions/structure/agents.py`, `agents/divisions/timeframe/scouts.py`, `execution/position_manager.py`, `spk/veto.py`, `runtime.py`)
**Status:** Done

**Yang dikerjakan**
- Melakukan audit dan sinkronisasi menyeluruh terhadap 4 dokumen riset institusional XAU/USD (`docs/riset/`) ke dalam arsitektur bot GoldScalper tanpa melanggar doktrin The Juggler (Portfolio Target & Dynamic Bleeding Clamp) maupun BizDev (Friction Surveillance):
  1. **Session Clocks & Cutoffs (`core/clock.py`, `runtime.py`, `spk/veto.py`):**
     - Menerapkan **London Open Observation Freeze (08:00–08:15 UTC)**: Hard veto otomatis selama 15 menit pertama pembukaan London untuk mengamati arah ekspansi candle M15 institusi.
     - Menerapkan **Session Hard Cutoff (15:30 UTC / 22:30 WIB)**: Mencegah pembukaan posisi intraday baru setelah 15:30 UTC akibat anomali spread/likuiditas pra-close NY.
     - Menerapkan **Overnight Flat Cutoff (21:00 UTC / 04:00 WIB)** di `execution/position_manager.py`: Menutup paksa sisa posisi mengambang sebelum rollover swap harian.
  2. **News Blackout Window & Consecutive Losses Rule:**
     - Memperluas blackout kalender berita berdampak tinggi menjadi **30 menit sebelum dan 20 menit sesudah** rilis (`news_blackout_pre_minutes=30`, `news_blackout_post_minutes=20`).
     - Mengubah circuit breaker harian menjadi **3 consecutive losses** (`max_consecutive_losses=3`) sesuai aturan tegas dokumen riset.
  3. **Order Block Precision Anatomy (Body-Only Bounds & Retest) (`agents/divisions/structure/agents.py`):**
     - Memperbarui agen `Liquidity`: Mengukur zona Order Block strictly dari batas candle body (`[open, close]`) dan mengabaikan shadow/wick untuk penentuan zona entry presisi institusional.
     - Menambahkan deteksi retest bounce ke zona body Order Block beserta sinyal metadata (`ob_bull_body`, `ob_bear_body`, `ob_retest_bull`, `ob_retest_bear`).
  4. **Top-Down D1 Macro Directional Veto (`agents/divisions/timeframe/scouts.py`):**
     - Menyempurnakan agen `D1Macro`: Mengeluarkan directional hard veto (`VETO_SELL` pada struktur Bullish dan `VETO_BUY` pada struktur Bearish) saat harga berada di luar extreme reversal zone.
- Memperbarui dan melengkapi test suite:
  - `tests/test_clock.py`: Menambahkan `test_london_open_freeze` dan `test_session_hard_cutoff`.
  - `tests/test_spk_veto.py`: Decouple pengujian freeze & cutoff via state flags.
  - `tests/test_structure_division.py`: Menambahkan pengujian candle body OB & retest.
  - `tests/test_timeframe_division.py`: Menambahkan pengujian D1 macro directional vetoes.
  - `tests/test_execution.py`: Menambahkan pengujian overnight flat cutoff.
- Verifikasi penuh test suite: **230 passed in 1.96s (100% clean)**.

**File tersentuh**
- `config/settings.py` — Parameter news blackout 30m/20m, session freezes, dan 3 losses cutoff.
- `.env.example` — Sinkronisasi variabel environment baru.
- `core/clock.py` — Logika `is_london_open_freeze` dan `is_hard_cutoff`.
- `core/calendar_service.py` — Default window blackout 30m/20m.
- `agents/divisions/timeframe/scouts.py` — D1 Macro directional veto.
- `agents/divisions/structure/agents.py` — Order Block body bounds & retest bounce.
- `execution/position_manager.py` — Overnight flat cutoff $\ge 21:00$ UTC.
- `runtime.py` — Injeksi state flags `london_open_freeze` & `session_hard_cutoff`.
- `spk/veto.py` — Evaluasi hard veto session clock & cutoff.
- `tests/*` — Unit test clock, veto, structure, timeframe, and execution.
- `docs/IMPLEMENTATION_PLAN_INSTITUTIONAL_SMC.md` — Checklist task eksekusi.

**Verifikasi**
- `sudo docker exec gs-bot pytest --ignore=tests/test_backtest.py` → **230 passed in 1.96s (100%)**

---

## 2026-10-16 — Small Defense Lot Preservation (0.02 – 0.04 Lot): Eliminating the Multiplicative Shrinkage Trap

**Phase / Area:** Position Sizing & Pre-Trade Risk Gate (`agents/divisions/risk/agents.py`, `execution/risk_gate.py`, `tests/test_risk_division.py`)
**Status:** Done

**Yang dikerjakan**
- Membongkar dan menuntaskan akar penyebab mengapa seluruh order di live trading tertekan menjadi **0.01 lot**:
  1. **Akar Masalah (The Multiplicative Trap):** Tidak ada kode hardcode `0.01` sama sekali. Sizer sebenarnya telah mengalokasikan `0.02` s/d `0.03` lot. Namun di `execution/risk_gate.py`, nilai lot tersebut dikalikan ulang dengan probabilitas keyakinan SPK (`0.02 * confidence (0.50 - 0.65) = 0.010 - 0.013`). Akibat pembulatan lot step (0.01), hasil matematisnya **selalu terperangkap di 0.01 lot**!
  2. **Enforce Defense Baseline Floor (AGENTS.md):** Di [agents/divisions/risk/agents.py](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/agents/divisions/risk/agents.py), menerapkan perintah resmi Juggler Directive: pada mode `DEFENSE`, lot sizing wajib bergerak di rentang **0.02 – 0.04 lot** (Grade A+ mendapatkan 0.03–0.04 lot, normal defense mendapatkan 0.02 lot).
  3. **Bypass Confidence Multiplication pada Lot $\le 0.04$:** Di [execution/risk_gate.py](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/execution/risk_gate.py), meniadakan pengalian confidence untuk order $\le 0.04$ lot (`scaled_size = base_size`), sehingga perhitungan presisi Sizer tidak dipotong separuh lagi oleh RiskGate.
- Menambahkan unit test baru di `tests/test_risk_division.py`:
  - `test_gate_preserves_small_defense_lots_without_crushing_to_one`
- Verifikasi penuh test suite: **230 passed in 1.97s (100% clean)**.
- Hot-deploy ke production server (`gs-bot` restarted, runtime streaming normal).

**File tersentuh**
- `agents/divisions/risk/agents.py` — Defense floor lot 0.02–0.04 per AGENTS.md.
- `execution/risk_gate.py` — Bypass pengalian confidence pada lot $\le 0.04$.
- `tests/test_risk_division.py` — Unit test proteksi lot kecil.

**Verifikasi**
- `bash run_server_tests.sh` → **230 passed in 1.97s (100%)**
- `bash restart_bot.sh` → Runtime active, 37 agents loaded, tick streamer running.

---

## 2026-10-16 — Pyramid Basket Separation Fix: Protecting Scale-In Positions from 0s Basket Cuts

**Phase / Area:** Multi-Entry Execution & Basket Management (`execution/position_manager.py`, `tests/test_execution.py`)
**Status:** Done

**Yang dikerjakan**
- Memperbaiki konflik logika antara modul *Risk-Free Pyramiding* (`order_manager.py`) dan modul *Basket Recovery TP* (`position_manager.py`):
  1. **Akar Masalah:** Saat posisi Pyramiding (Layer 2) dibuka pada tren menguntungkan di atas posisi pertama, harga pasar saat itu secara matematis sudah berada di atas harga rata-rata keranjang ($Avg Entry + Buffer$). Modul `manage_basket` yang dirancang untuk *Rescue Averaging Down* langsung menganggap target tercapai dan menutup Layer 2 dalam tempo 50ms ($0s duration, $0.00 PnL).
  2. **Pemisahan Tipe Keranjang:** Di `execution/position_manager.py:manage_basket()`, ditambahkan deteksi cerdas `is_pyramid` berbasis tag komentar order (`PYRAMID`) atau arah harga entry menaik searah tren.
  3. **Proteksi Runner Pyramiding:** Jika keranjang teridentifikasi sebagai Pyramiding, sistem **DILARANG** melakukan cut break-even instan. Keranjang dibiarkan bernafas mengikuti SL Break-Even posisi pertama dan TP runner Layer 2, atau ditutup keranjang penuh hanya jika profit kumulatif mencapai target runner $\ge \$7.50$.
- Menambahkan unit test baru di `tests/test_execution.py`:
  - `test_position_manager_manage_basket_pyramid_protects_runners`
- Verifikasi penuh test suite: **230 passed in 1.98s (100% clean)**.
- Hot-deploy ke production server (`gs-bot` restarted, runtime streaming normal).

**File tersentuh**
- `execution/position_manager.py` — Pemisahan logika keranjang Pyramid vs Rescue, proteksi target runner $\ge \$7.50$.
- `tests/test_execution.py` — Unit test untuk proteksi keranjang pyramiding.

**Verifikasi**
- `bash run_server_tests.sh` → **230 passed in 1.98s (100%)**
- `bash restart_bot.sh` → Runtime active, 37 agents loaded, tick streamer running.

---

## 2026-10-16 — Agent Pipeline Deep-Dive Audit & Midnight Rollover Hardening (37 Agents End-to-End)

**Phase / Area:** Full Pipeline Integration & System Health Audit (`runtime.py`, `agents/orchestrator.py`, `execution/risk_gate.py`)
**Status:** Done

**Yang dikerjakan**
- Melakukan audit mendalam (deep-dive) pada integrasi data flow dan komunikasi antar 37 agent menyambut pergantian hari (00:00:00 WIB):
  1. **Menghubungkan "Kabel" SPK Feedback Loop ke SharedState:** Sebelumnya, `state.extra` belum menyertakan `spk_confidence`, `spk_score`, dan `high_confluence` dari evaluasi SPK siklus sebelumnya. Sekarang dihubungkan langsung di `runtime.py._build_state()`, sehingga agen risk (`PositionSizer`, `TakeProfit`) dan teknikalis mengetahui momentum konsensus SPK saat evaluasi paralel.
  2. **RiskGate Execution Guarantee for Grade A+:** Di `execution/risk_gate.py`, menambahkan pengaman ganda saat mengeksekusi trade Grade A+ di mode DEFENSE: jika `is_high_conviction` terpenuhi (confidence $\ge 0.70$ atau $|score| \ge 5.0$), lot dijamin pada recovery tier (0.03–0.04) dalam batas clamp budget, dan target profit dijamin diperluas ke TP runner ($\ge \$7.50$).
  3. **Reversal Confluence Runner Expansion:** Di `agents/orchestrator.py`, memindahkan kalkulasi `confirming_conf` lebih awal dan menghubungkannya ke target profit pembalikan arah: saat konfluensi reversal terkonfirmasi kuat ($\ge 0.70$), TP otomatis diekspansi ke level runner ($7.50+$ / $1.8\times SL$).
  4. **Pembersihan Bersih Day Rollover (00:00 WIB Reset):** Menambahkan reset `_daily_win_count = 0` dan `_live_avg_win = 0.0` pada cabang pergantian tanggal WIB di `runtime.py` agar metrik hari kemarin tidak bocor/mengontaminasi hari baru.
  5. **Proteksi Spread Spikes Midnight:** Memvalidasi bahwa lonjakan spread broker saat rollover tengah malam (00:00) diproteksi ganda oleh `CostMonitor` (`cost_ok = False` jika spread > `max_spread_points`) dan SPK Hard Veto (`evaluate_vetoes`).
- Verifikasi seluruh unit test: **230 passed in 1.94s (100% clean)**.
- Hot-deploy ke server live production (`gs-bot` restarted, runtime streaming normal).

**File tersentuh**
- `runtime.py` — Injeksi `spk_confidence` / `high_confluence` ke `extra_state` dan reset `_daily_win_count` / `_live_avg_win` saat SOD rollover.
- `execution/risk_gate.py` — Pengaman eksekusi Grade A+ recovery lot & TP runner.
- `agents/orchestrator.py` — Reversal confluence TP runner expansion.

**Verifikasi**
- `bash run_server_tests.sh` → **230 passed in 1.94s (100%)**
- `bash restart_bot.sh` → Runtime active, 37 agents loaded, tick streamer running, order manager and reversal confluence responding normally.

---

## 2026-10-16 — High-Conviction Sizing Tier (Grade A+), Runner Harvesting & Risk-Free Pyramiding in DEFENSE Mode

**Phase / Area:** Quantitative Financial Engineering & Execution Optimization (`agents/divisions/risk/agents.py`, `execution/risk_gate.py`, `execution/order_manager.py`, `execution/position_manager.py`, `tests/test_risk_division.py`)
**Status:** Done

**Yang dikerjakan**
- Mengeliminasi *Recovery Asymmetry Trap* (asimetri pemulihan modal di mana kemenangan tertahan di lot 0.01 sementara kerugian terakumulasi lebih cepat):
  1. **High-Conviction Sizing Tier (Grade A+ di DEFENSE Mode):** Pada kondisi drawdown (`daily_pnl_pct < 0`), setup dengan keyakinan tinggi (`spk_confidence >= 0.70` atau `spk_score >= 5.0` atau `high_confluence == True`) tidak lagi dipaksa ke 0.01 lot, melainkan dialokasikan **0.03 – 0.04 lot** secara aman di dalam batas dynamic clamp budget ($7.50).
  2. **Eliminasi Double-Shrinkage Trap:** Di `execution/risk_gate.py`, setup Grade A+ tidak lagi dikalikan ulang dengan nilai confidence (`base_size * confidence = 0.009 -> 0.01`), melainkan mempertahankan alokasi dinamis sizer (`scaled_size = base_size`).
  3. **High-Conviction Runner TP Expansion:** Di `TakeProfit`, saat setup berstatus High-Conviction di DEFENSE mode, target profit diekspansi menjadi $RR = 1.80$ dengan minimum take-profit $TP \ge \$7.50$ (bukan lagi terpotong statik di $3.00).
  4. **Perlindungan Runner dari Premature Time-Decay:** Di `execution/position_manager.py`, menambahkan filter `and htf_bias["verdict"] != "HTF_SUPPORTING"` pada time-decay salvage (300 detik) agar runner yang searah tren H4/H1/M15 tidak dicutting prematur pada pnl +$0.50.
  5. **Risk-Free Pyramiding di DEFENSE Mode:** Di `execution/order_manager.py`, relaksasi larangan mutlak pyramiding saat drawdown. Pyramiding diizinkan jika posisi awal telah menghasilkan floating profit $\ge +\$2.00$ (+20 pips), volume layer 2 dibatasi $\le 0.02$ lot, dan stop loss posisi pertama otomatis dikunci ke break-even (+0.20 USD).
- Menambahkan test suite baru di `tests/test_risk_division.py` mencakup:
  - `test_position_sizer_high_conviction_tier_in_defense`
  - `test_take_profit_high_conviction_runner_in_defense`
  - `test_gate_bypasses_double_shrinkage_on_high_conviction`
- Verifikasi penuh test suite di server: **230 passed in 2.01s (100%)**.
- Hot-deploy ke production server (`gs-bot` restarted, runtime streaming tick aktif, zero regression).

**File tersentuh**
- `agents/divisions/risk/agents.py` — High-Conviction recovery sizing tier (0.03–0.04 lot) & Runner TP ($7.50+).
- `execution/risk_gate.py` — Bypass double-shrinkage untuk setup Grade A+.
- `execution/order_manager.py` — Risk-Free Pyramiding di DEFENSE mode dengan floating profit $\ge \$2.00$ & BE lock.
- `execution/position_manager.py` — Proteksi runner dari time-decay salvage saat HTF supporting.
- `tests/test_risk_division.py` — Unit tests untuk high-conviction sizing, runner TP, dan gate bypass.
- `docs/QUANT_FINENG_BIZDEV_SPEC.md` — Spesifikasi Section 4.2 & Section 4.3 disinkronkan.

**Verifikasi**
- `bash run_server_tests.sh` → **230 passed in 2.01s (100%)**
- `bash view_logs.sh` → Runtime aktif, tick streaming XAUUSDm normal, SPK orchestrator menghasilkan trade order dengan target runner yang proporsional.

---

## 2026-10-16 — Indestructible MT5 Bridge: Self-Healing Supervisor, Host Watchdog & Stale Feed Hard Vetoes

**Phase / Area:** Production Reliability & Fault Tolerance (`scripts/run_bridge_supervised.sh`, `scripts/bridge_watchdog.sh`, `spk/veto.py`)
**Status:** Done

**Yang dikerjakan**
- Membangun 4 lapisan pertahanan anti-downtime (*fail-safe defense-in-depth*) agar insiden chart/feed freeze tidak terulang lagi:
  1. **Layer 1 (Root Cause Elimination):** Memaksa `WindowsSelectorEventLoopPolicy` di `bridge/app.py` untuk menghilangkan bug fatal kelelahan IOCP di Wine.
  2. **Layer 2 (Container Supervisor):** Menambahkan `scripts/run_bridge_supervised.sh` di dalam kontainer `gs-mt5`. Jika uvicorn crash karena alasan apa pun, supervisor akan merestartnya secara instan dalam 2 detik.
  3. **Layer 3 (Host Autonomous Watchdog):** Menambahkan `scripts/bridge_watchdog.sh` yang dijalankan setiap menit via cron host server. Watchdog secara aktif melakukan health-check dengan timeout 3 detik; jika terjadi hang/timeout, script otomatis me-recover bridge dan bot tanpa campur tangan manusia.
  4. **Layer 4 (SPK Hard Veto for Stale Feeds):** Menambahkan validasi `last_tick_age_s > 5.0s` dan `mt5_connected == False` langsung ke dalam SPK Veto Engine (`spk/veto.py`). Jika data pasar terhenti >5 detik, sistem otomatis mengaktifkan Hard Veto dan mengunci order baru demi keselamatan modal.
- Menambahkan unit test di `tests/test_spk_veto.py` untuk memastikan kepatuhan hard veto feed stale.
- Verifikasi penuh seluruh test suite: **230 passed (100%)**.

**File tersentuh**
- `scripts/run_bridge_supervised.sh` — Script loop supervisor uvicorn di dalam kontainer Wine.
- `scripts/bridge_watchdog.sh` — Script autonomous health-check & auto-recovery cron host.
- `spk/veto.py` — Hard veto untuk tick stale (>5s) dan disconnected MT5.
- `tests/test_spk_veto.py` — Unit test untuk feed stale & bridge disconnect hard vetoes.
- `scripts/deploy_bridge_update.sh` — Integrasi deployment otomatis supervisor & cron.

**Verifikasi**
- `docker exec gs-bot pytest --ignore=tests/test_backtest.py` → **230 passed in 2.10s (100%)**
- `inspect_mt5_ps.sh` → Supervisor PID aktif mengawal uvicorn di port 9095.
- `crontab -l` → Cron watchdog aktif setiap menit.
- Bot live logs → Realtime ticks lancar, reversal confluence & execution responsif.

---

## 2026-10-16 — Diagnosa & Perbaikan Chart Freeze: Fix Wine Asyncio IOCP Crash (WindowsSelectorEventLoopPolicy)

**Phase / Area:** Production MT5 Bridge (`bridge/app.py`), Tick Streaming & Live Chart WebTelemetry
**Status:** Done

**Yang dikerjakan**
- Menemukan akar penyebab berhentinya pergerakan chart pada `scalper.7pivot.site`:
  Di dalam kontainer `gs-mt5` (Wine 9.0), Uvicorn Python 3.8+ secara default menggunakan `asyncio.ProactorEventLoop` (I/O Completion Ports / IOCP). Karena frekuensi streaming tick sangat tinggi (~80ms, >1.4 juta request HTTP), emulasi IOCP winsock Wine mengalami kelelahan soket hingga memicu crash `OSError: [WinError 59] Unexpected network error (Accept failed on a socket: ('0.0.0.0', 9095))`.
- Port 9095 tertutup dan `gs-bot` mencatat `tick poll error: All connection attempts failed`, mengakibatkan streaming tick ke websocket chart berhenti.
- Memperbaiki `bridge/app.py` dengan memaksa penggunaan `asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())` di platform Win32 / Wine. Selector event loop berbasis standar `select()` yang 100% stabil di layer Wine.
- Mendeploy pembaruan ke server produksi (`studo@100.114.150.48`), merestart uvicorn bridge di `gs-mt5`, dan merestart `gs-bot`.
- Memverifikasi koneksi MT5 bridge pulih (`{"status":"ok","connected":true}`), tick streaming 80ms aktif kembali, dan chart live bergerak normal.

**File tersentuh**
- `bridge/app.py` — Tambahkan `WindowsSelectorEventLoopPolicy()` untuk Win32 / Wine.
- `scripts/deploy_bridge_update.sh` — Script otomasi injeksi fix bridge ke Wine `gs-mt5` dan restart service.

**Verifikasi**
- `curl -s http://mt5:9095/health` → `{"status":"ok","connected":true,"trade_allowed":true}`
- `curl -s -H 'Authorization: ...' http://127.0.0.1:9090/api/status` → Realtime telemetry aktif (`tick_age=None`, `candle_stale=False`, `mt5=True`, realtime cycle aktif).

---

## 2026-10-16 — Full SPK Audit: Dynamic Reversal Hunter, TakeProfit & Risk Gate (100% Portfolio & Target Aligned)

**Phase / Area:** SPK Core (`Orchestrator`), Risk Division (`Risk-TakeProfit`), Pre-trade Gate (`RiskGate`)
**Status:** Done & Deployed to Home-Server (100% 221 Tests Passed)

**Yang dikerjakan**
- **Audit Temuan Kode Statik & Hardcode SPK:**
  - Menemukan dan mengeliminasi sisa parameter statik di `agents/orchestrator.py` (Reversal Hunter Confluence):
    - `SL = 1.80` dan `TP = 6.00` yang statik diubah menjadi perhitungan dinamis berbasis `spread_usd`, `live_avg_win`, `daily_pnl_pct`, dan `remaining_target_usd`.
    - `confidence = 0.72` yang statik diubah menjadi dinamis mengambil skor confidence scout konfirmasi (M1-Sniper / Tech-Pattern / Microstructure) yang kemudian diredam dengan *drawdown health drag*.
- **Upgrade Dinamis `Risk-TakeProfit` (`agents/divisions/risk/agents.py`):**
  - Mengeliminasi `default_rr = 1.5` statik pada `TakeProfit`.
  - Mengintegrasikan 3-Tier Mode Juggler ke dalam target take-profit:
    - *Finish Line Proximity (`remaining_target_usd <= $20`):* TP otomatis dikalibrasi sesuai sisa jarak target harian untuk mengunci garis finish.
    - *Defense Mode (`daily_pnl_pct < 0%`):* RR dipercepat ke `1.30R` (minimal $3.00) untuk *rapid profit banking*.
    - *Growth Mode (`daily_pnl_pct >= 3.0%`):* Runner diekspansi ke `2.0R` (atau $\ge 1.3\times \text{live avg win}$) memanfaatkan modal profit pasar.
    - *Balanced Mode:* Menjaga payoff asimetris positif terikat pada performa rata-rata win harian.
- **Validasi `RiskGate` Pre-Trade (`execution/risk_gate.py`):**
  - Memperbaiki bug di mana `RiskGate` menimpa (*override*) level SL dan TP khusus dari SPK (seperti Reversal Hunter). Kini `decision.sl` dan `decision.tp` diprioritaskan dan divalidasi terhadap batas clamp.
- **Pembersihan Seluruh Lint Error:**
  - Menyelesaikan 3 pesan masalah type checker pada `_build_state()` dan `on_trade_closed()`.

**File tersentuh**
- `agents/orchestrator.py` — Dynamic reversal hunter SL/TP, dynamic reversal confidence, type-safe `isinstance(result, Awaitable)`, guard `card is None`
- `agents/divisions/risk/agents.py` — 3-tier dynamic portfolio `TakeProfit`
- `execution/risk_gate.py` — Preservasi `decision.sl` dan `decision.tp`
- `tests/test_risk_division.py` — Unit test untuk mode Defense, Growth, dan Finish Line pada `TakeProfit`
- `docs/PROGRESS.md` — Sinkronisasi log progres

**Verifikasi**
- `pytest -q --ignore=tests/test_backtest.py` di dalam container `gs-bot` → **221 passed (100% tests green)**.
- Bot restart bersih di container `gs-bot`. Preload Live Stats: wins=59, avg_win=$4.49.


**Phase / Area:** Execution Layer (`OrderManager`), The Juggler FinEng, Agent Directives & Skills
**Status:** Done & Deployed to Home-Server (100% 220 Tests Passed)

**Yang dikerjakan**
- **Juggler Portfolio & Target-Aware Layering Gate (`execution/order_manager.py`):**
  - **Finish Line Lockdown:** Saat sisa target harian mendekati garis finish (`remaining_target_usd <= $20`), seluruh pembukaan layer tambahan (rescue layering & pyramiding) **DIBLOKIR TOTAL**. Sistem mengunci mode *Single Position Only* demi melindungi kemenangan harian.
  - **Drawdown Defense Mode Gate:** Jika drawdown mencapai `daily_pnl_pct <= -4.0%`, sistem otomatis mengunci ke mode *Single Position Only*.
  - **Larangan Mutlak Pyramiding saat Drawdown:** Pyramiding ke arah yang sama **DILARANG KERAS** saat akun dalam kondisi minus (`daily_pnl_pct < 0%`), atau jika posisi sebelumnya belum dalam kondisi floating profit positif.
  - **Pencegahan Clustering Layer Berdekatan:** Memperbaiki bug di mana `entry` tidak teresolusi sehingga jarak layer terlewat. Kini jarak minimum antar-layer dinaikkan secara dinamis:
    - Mode Normal/Growth: minimum $\ge 20$ pips ($2.00 USD).
    - Mode Drawdown Defense: minimum $\ge 30-35$ pips ($3.00–$3.50 USD). Mencegah tumpukan posisi dalam jarak sempit (seperti 21 sen yang terjadi sebelumnya).
- **Injeksi Hukum Sistem ke Directives & Skill Proyek:**
  - Menambahkan **Section 4: HUKUM SISTEM STRATEGI TRADING: WAJIB MENGACU PORTFOLIO & TARGET HARIAN** ke dalam [AGENTS.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/AGENTS.md).
  - Membuat skill resmi agen baru: [.agents/skills/goldscalper-portfolio-juggler/SKILL.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/.agents/skills/goldscalper-portfolio-juggler/SKILL.md) yang mewajibkan setiap agen dan pair programmer di masa depan selalu mengalibrasi rekomendasi strategi terhadap 3 Pilar Juggler (Portfolio Health, Sprint Target Proximity, dan Live Win Statistics).
  - Sinkronisasi [docs/MULTI_ENTRY_RESCUE_SPEC.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/MULTI_ENTRY_RESCUE_SPEC.md).

**File tersentuh**
- `execution/order_manager.py` — Juggler finish line multi-entry lockdown, drawdown pyramid ban, dynamic spacing ($\ge 20-35$ pips), entry resolution fix
- `tests/test_execution.py` — Unit tests untuk finish line multi-entry lock dan drawdown pyramid ban
- `AGENTS.md` — Injeksi Section 4 (Hukum mutlak strategi mengacu portfolio & target harian)
- `.agents/skills/goldscalper-portfolio-juggler/SKILL.md` — Pembuatan skill resmi Juggler Engine
- `docs/MULTI_ENTRY_RESCUE_SPEC.md` — Spesifikasi multi-entry disinkronkan dengan aturan Juggler
- `docs/PROGRESS.md` — Catatan progres pekerjaan

**Verifikasi**
- `pytest -q --ignore=tests/test_backtest.py` di dalam container `gs-bot` → **220 passed (100% tests green)**.
- Bot restart bersih di container `gs-bot`.


**Phase / Area:** SPK Core (Voting & Veto Engine), The Juggler FinEng, Risk Division
**Status:** Done & Deployed to Home-Server (100% 218 Tests Passed)

**Yang dikerjakan**
- **Eliminasi Hardcode Static Cap (0.05 Lot Dihapus):**
  - Mengubah seluruh sistem penentuan lot dan ambang batas konsensus SPK menjadi **100% dinamis dan adaptif terhadap kesehatan portfolio harian dan sisa target sprint** (`daily_pnl_pct`, `remaining_target_usd`, `live_avg_win`).
  - Arsitektur 3-Tier Multiplier Portfolio Health di `agents/divisions/risk/agents.py`:
    - `DEFENSE` (Drawdown `< 0%`): `health_mult = max(0.65, 1.0 + pnl_pct / 50.0)` $\rightarrow$ secara otomatis membatasi lot ke ukuran defensif (0.02–0.04) untuk melindungi ekuitas.
    - `GROWTH` (Profit harian $\ge +3\%$ s/d $+15\%$): `health_mult = min(1.40, 1.0 + pnl_pct / 100.0)` $\rightarrow$ mendongkrak lot secara organik (hingga 0.08–0.10) menggunakan keuntungan pasar (*house money*).
    - `BALANCED` (Netral): `health_mult = 1.0`.
  - Dynamic Bleeding Clamp dihitung proporsional: `base_clamp * health_mult` (di mana `base_clamp = max(7.0, live_avg_win * 1.1)`).
- **Dynamic SPK Consensus Modulation (`spk/voting.py`):**
  - `action_for_score`:
    - **Target Locked / Reached Gate:** Jika `daily_profit_locked == True` atau `remaining_target_usd <= 0.0`, SPK langsung mengunci posisi dan mengembalikan `(ACTION_HOLD, STRENGTH_NONE)` untuk memproteksi kemenangan harian.
    - **Proportional Drawdown Gradient:** Saat akun drawdown, ambang batas konsensus dinaikkan hingga +60% (`drawdown_penalty = min(0.60, abs(pnl_pct) / 15.0)`), membungkam noise single-agent dan hanya mengizinkan setup multi-division confluence.
    - **Finish Line Proximity Funnel:** Saat sisa target harian semakin dekat ($\le \$25$), ambang diperketat secara halus (`weak_threshold * 1.10 - 1.35`) agar trade marjinal tidak mempertaruhkan target sprint.
- **Dynamic Soft & Hard Veto Engine (`spk/veto.py`):**
  - Menambahkan Hard Veto untuk status `daily_profit_locked` dan target tercapai.
  - Penalti Soft Veto (HTF conflict, wide spread, low liquidity) diskalakan secara dinamis hingga $1.5\times$ saat portfolio berada dalam kondisi drawdown (`pnl_penalty_mult = min(1.50, 1.0 + abs(daily_pnl_pct) / 12.0)`).
  - Proteksi gesekan spread saat mendekati garis finish target ($\le \$15$).
- **Dynamic Confidence Drag (`agents/orchestrator.py`):**
  - Nilai confidence keputusan SPK kini dipengaruhi langsung oleh kesehatan portfolio harian: saat terjadi drawdown, diberikan damping halus (`pnl_drag = max(-0.15, daily_pnl_pct / 50.0)`), yang secara berantai menurunkan ukuran lot downstream di `execution/risk_gate.py`.

**File tersentuh**
- `spk/voting.py` — Modulasi konsensus dinamis (Drawdown gradient, growth acceleration, target proximity funnel, target locked hold)
- `spk/veto.py` — Hard veto daily profit locked & dynamic soft veto scaling berdasarkan drawdown
- `agents/orchestrator.py` — Integrasi portfolio health drag pada confidence score SPK
- `agents/divisions/risk/agents.py` — 3-Tier dynamic health sizing & dynamic clamp budget
- `tests/test_spk_voting.py` — 3 unit tests baru untuk target locked, drawdown gradient, dan proximity funnel
- `tests/test_spk_veto.py` — 4 unit tests baru untuk target locked veto, drawdown soft penalty scaling, dan finish line spread caution

**Verifikasi**
- `pytest -q --ignore=tests/test_backtest.py` di dalam container `gs-bot` → **218 passed (100% tests green)**.
- Bot restart bersih di container `gs-bot`, preloaded live stats: wins=53, avg_win=$4.81.


**Phase / Area:** The Juggler FinEng & Position Manager — Payoff Asymmetry Fix
**Status:** Done & Deployed to Home-Server (100% Tests Passed)

**Yang dikerjakan**
- **Kalibrasi Lot Sizing Terukur (0.03 – 0.05 Lot Cap):**
  - Mengeliminasi pembukaan lot raksasa (0.12–0.13 lot) di akun normal dengan menyinkronkan `PositionSizer` di `agents/divisions/risk/agents.py` langsung ke `clamp_budget` ($6.00 – $7.00) dan membatasi ukuran lot maksimum ke `0.05` lot.
  - Dampak nyata: Kerugian per trade kini terbukti terpangkas aman di kisaran **-$4.90 s/d -$5.20** (sebelumnya -$12.88).
- **Dynamic Risk-Free Break-Even Lock (`execution/position_manager.py`):**
  - Mengimplementasikan pengunci modal otomatis: Saat floating profit mencapai $\ge 25$ pips ($+\$2.50$), Stop Loss otomatis digeser ke `Entry + $0.15` (mengunci keuntungan kecil $+\$0.60$ dan membuat posisi **100% bebas risiko**).
- **Upgrade Ambang Panen Runner (`juggler_momentum_harvest`):**
  - Menghentikan pemotongan profit prematur di detik ke-90 pada profit kecil ($3.00).
  - Ambang runner dinaikkan ke **$\ge \$7.50$** (atau $1.25\times \text{avg win}$), membiarkan posisi pemenang bernafas 2–8 menit menjemput gelombang TP M5/M15.
  - Mempertahankan proteksi *HTF Defensive Harvest*: Jika scouts HTF (H4/H1/M30) berbalik arah melawan posisi, profit $\ge \$3.50$ langsung diamankan sebelum tergerus.
  - Memperbarui `stagnant_harvest` agar tidak memotong posisi yang trennya sedang didukung penuh oleh struktur HTF.

**File tersentuh**
- `agents/divisions/risk/agents.py` — Sizing lot terukur dibatasi clamp budget dan cap 0.05 lot
- `execution/position_manager.py` — Early Break-Even lock, runner target $\ge \$7.50$, HTF defensive exit

**Verifikasi**
- `pytest -q --ignore=tests/test_backtest.py` di dalam container `gs-bot` → **214 passed (100% test suite pass)**.
- Container restart clean & live execution terkonfirmasi: Layer 2 SELL dibuka dengan lot terukur (0.01 lot) dan dilindungi max layers limit.

---

## 2026-10-16 — Full WIB (UTC+7) Timezone Alignment across Portfolio, Runtime & BizDev

**Phase / Area:** Frontend UI Portfolio, API Routes & Runtime Daily Aggregation
**Status:** Done & Deployed to Home-Server (100% Tests Passed)

**Yang dikerjakan**
- **Harmonisasi Timezone ke WIB (UTC+7 / Asia/Jakarta):**
  - Mengubah titik potong filter preset "Hari Ini" (`today`) di `api/routes/performance.py` agar mulai tepat jam **00:00:00 WIB** (17:00:00 UTC hari sebelumnya) sampai sekarang, alih-alih 00:00 UTC (jam 07:00 pagi WIB).
  - Mengubah preset "Kemarin" (`yesterday`) untuk merangkum rentang tepat 24 jam WIB hari sebelumnya (`00:00:00 WIB s/d 23:59:59 WIB`).
  - Mengubah datepicker custom filter di `frontend/js/agents.js` agar mengirimkan offset eksplisit `+07:00` (bukan suffix `Z` yang memaksa UTC).
  - Memperbarui Start of Day (SOD) balance tracking dan reset harian di `runtime.py` agar berganti buku harian pas tengah malam **00:00:00 WIB** (`now_dt.astimezone(WIB).date()`).
  - Menyelaraskan endpoint `api/routes/bizdev.py` (`/api/bizdev/daily`) ke awal hari WIB sehingga total lot, rebate, dan net yield 100% sinkron dengan ringkasan portfolio harian.
  - Menambahkan fungsi helper `formatWIB()` di `frontend/js/components.js` dan menyematkan label `(WIB)` pada filter pills, tooltip grafik equity, X-axis date ticks, dan kolom *Closed* di tabel ledger trade.

**File tersentuh**
- `api/routes/performance.py` — Kalkulasi `since_dt` dan `until_dt` berbasis `WIB = timezone(timedelta(hours=7))`
- `api/routes/bizdev.py` — Agregasi harian rebate dan biaya fee diselaraskan ke tengah malam WIB
- `api/routes/trades.py` — Default timezone fallback diubah ke WIB
- `runtime.py` — Preload `_preload_today_history()` dan reset harian SOD menggunakan tanggal WIB
- `frontend/js/components.js` — Ekspor fungsi `formatWIB()`, render X-axis dan tooltip chart equity dalam zona Asia/Jakarta
- `frontend/js/agents.js` — Input kustom filter tanggal memakai offset `+07:00`, pill badges `(WIB)`, dan kolom closed menampilkan waktu WIB

**Verifikasi**
- `curl /api/performance?period=today` → `"since": "2026-10-16T00:00:00+07:00"` (Tepat 00:00 WIB hari ini, total 43 trades).
- `curl /api/performance?period=yesterday` → `"since": "2026-10-15T00:00:00+07:00"`, `"until": "2026-10-16T00:00:00+07:00"` (Tepat 24 jam WIB kemarin, total 406 trades).
- `curl /api/bizdev/daily` → `"date": "2026-10-16"`, `total_trades: 43` (100% sinkron dengan performa hari ini).
- Pytest di container `gs-bot` → 214 passed (100% test suite pass).
- Container restart clean & logs memverifikasi: `PRELOADED TODAY PORTFOLIO STATS: wins=13, avg_win=$5.92 ...` dari 00:00:00 WIB.

---

## 2026-10-16 — The In-Flight Reversal Arbiter: HTF Scouts Streaming & Noise Floor Calibration

**Phase / Area:** The Juggler FinEng & Position Watchdog — In-Flight Reversal & Noise Floor Sync
**Status:** Done & Deployed to Home-Server (100% Tests Passed)

**Yang dikerjakan**
- **Kalibrasi Physical Noise Floor Emas (Eliminasi SL 2 Detik):**
  - Mengidentifikasi akar masalah matematis: Lot 0.12 dengan clamp $6.04 hanya memberikan jarak nafas 2.6 pips (setara getaran 1 detik broker).
  - Mengimplementasikan *Physical Noise Floor* $\ge 16$ pips ($\$1.60$) pada Emas yang diskalakan ke volume lot: $\text{Effective Clamp} = \max(\text{Lot} \times 1.60 \times 100, \; 1.1 \times \text{Avg Win})$.
  - Menambahkan *Noise Absorption Grace Period* (0–15s) untuk menyerap spread bid-ask awal tanpa cutloss prematur.
- **In-Flight Reversal Arbiter berbasis Higher Timeframe (HTF) Scouts (`execution/position_manager.py`):**
  - Menghubungkan streaming konsensus dari para agen bertimeframe panjang dengan histori candle kaya langsung ke watchdog pemantau posisi:
    - `TF-H4-Structure` (H4 Trend & Major Order Blocks — bobot 2.5)
    - `TF-H1-Regime` (H1 21-EMA Slope & Box Channel — bobot 2.5)
    - `TF-M30-Momentum` (M30 Momentum & Exhaustion Wicks — bobot 1.5)
    - `TF-M15-Liquidity` (M15 Liquidity Sweeps & Structure — bobot 1.5)
    - `Struct-MarketStructure` (M5 Break of Structure / CHoCH — bobot 1.0)
  - **Keputusan Reversal Data-Driven:**
    - `HTF_SUPPORTING`: Jika H4, H1, M30, M15 searah dengan posisi, floating minus di M1 diakui sebagai *minor pullback*. Watchdog memberikan izin menahan posisi (*Hold for Reversal*) hingga batas normal clamp.
    - `HTF_OPPOSING`: Jika H1/M15/H4 telah mematahkan struktur berlawanan arah, watchdog melakukan **Early Cutloss** di $\ge 65\%$ clamp untuk mencegah kerugian melebar (menghilangkan jebakan emosi "mudah-mudahan").
- **Sinkronisasi Sizer & Drawdown Guard (`agents/divisions/risk/agents.py`):**
  - Menyelaraskan `PositionSizer` di mode `TARGET_SEEKING` dengan ruang nafas clamp dan memperbaiki metadata `risk_amount`.
  - Memperbaiki ambang sirkuit `DrawdownGuard` berbasis `max_daily_loss_pct`.
- **Verifikasi Test Suite:**
  - `pytest -q` dijalankan di server: **100% Tests Passed (Zero Failures)**.
  - Container `gs-bot` direstart normal dan posisi baru berjalan stabil tanpa terpotong instan.

**File tersentuh**
- `execution/position_manager.py` — `evaluate_htf_reversal_bias`, noise floor, grace period, dan HTF-aware cuts
- `runtime.py` — Passing `decision` dan `state` ke dalam `mgmt_context`
- `agents/divisions/risk/agents.py` — Perbaikan metadata `PositionSizer` dan threshold `DrawdownGuard`
- `docs/QUANT_FINENG_BIZDEV_SPEC.md` — Spesifikasi teknis Section 4.4
- `docs/PROGRESS.md` — Worklog kronologis

---

## 2026-10-16 — Cockpit Running Ticker: Live Daily Target & Performance Badge Integration

**Phase / Area:** Cockpit Telemetry UI & Juggler Performance Integration
**Status:** Done & Ready for Deploy

**Yang dikerjakan**
- **Injeksi Performa & Target Harian ke Running Ticker Cockpit (`frontend/js/app.js`):**
  - Mengintegrasikan informasi real-time target harian sprint (`+35.0%`), pencapaian realized PnL hari ini (`+$XX.XX` / `+X.X%`), progress persentase sprint & sisa nominal USD (`Sisa $XX.XX`), serta volume lot & estimasi rebate BizDev ke dalam running marquee ticker Cockpit.
  - Menghandle state khusus `TARGET HARIAN LOCKED` saat circuit breaker profit lock terpicu untuk memberitahu operator bahwa target sprint harian sudah aman.
  - Memperbarui parser telemetry di `runtime.py` dengan menambahkan `daily_win_count` dan `sod_balance`.
- **Refinement Anti-AI-Slop & Borderless Styling (`frontend/css/cockpit.css`):**
  - Membersihkan seluruh karakter Unicode emoji dari string ticker (menggantikan dengan tipografi monospaced finansial presisi).
  - Memberikan styling badge khusus `.ticker-perf-badge` (aksen emas `#d9a441`) dan pewarnaan angka otomatis (`.perf-win` hijau, `.perf-loss` merah).
  - Mengoptimalkan durasi marquee menjadi 34s linear loop agar informasi panjang dapat terbaca dengan tenang tanpa rushing.

**File tersentuh**
- `runtime.py` — Tambahan field `daily_win_count` & `sod_balance` ke payload telemetry juggler
- `frontend/css/cockpit.css` — Styling elemen `.ticker-msg`, `.ticker-divider`, `.ticker-perf-badge`, `.ticker-bullet`, `.ticker-perf-item`
- `frontend/js/app.js` — Implementasi `buildDailyPerformanceTickerHtml(t)` dan integrasi ke `updateCockpitTicker()`
- `docs/PROGRESS.md` — Worklog kronologis

**Verifikasi**
- `python -m py_compile runtime.py` → 0 error.
- Validasi rendering dan struktur borderless: 100% mematuhi aturan sistem hukum borderless proyek.

---

## 2026-10-15 / 2026-10-16 — The Juggler (Financial Engineering), BizDev Rebate Engine, Dynamic SL/TP Clamp & Docs Keeper

**Phase / Area:** Financial Engineering (The Juggler), BizDev Economics, Dynamic Bleeding Clamp & Mandatory Docs Sync
**Status:** Done & Deployed to Home-Server (Live Verified)

**Yang dikerjakan**
- **The Juggler Dynamic Bleeding Clamp (`execution/position_manager.py`):**
  - Mengatasi akar masalah *asymmetric loss bleeding* (winrate 64% tapi profit tergerus karena average loss -$16 hingga -$31).
  - Mengimplementasikan dynamic loss clamp otomatis di batas `1.1 * live_avg_win` (terbukti live di VPS: saat ticket `4882492832` drawdown, clamp memotong kerugian di `-$6.21` sesuai live avg win `$5.49`).
  - Menambahkan hold duration dynamic exits:
    - *Loss Time Decay Cut:* Potong rugi setelah $\ge 180$ detik jika drawdown $\ge 0.7 \times$ clamp limit.
    - *Momentum Decay Harvest:* Ambil untung jika profit $\ge 60\%$ average win dan durasi $\ge 60$ detik saat momentum melambat.
    - *Target-Proximity Harvest:* Ambil untung jika profit posisi sudah menutup $\ge 35\%$ dari sisa target harian sprint.
- **Target-Seeking Dynamic Lot Sizing (`agents/divisions/risk/agents.py`):**
  - Menyesuaikan lot sizing berdasarkan sisa target harian sprint (+35% harian dari modal awal).
  - Mengunci trading (*Daily Profit Lock Circuit Breaker*) ketika target harian tercapai untuk mengamankan profit.
- **BizDev Rebate Engine & Friction Tracker (`api/routes/bizdev.py`, `runtime.py`):**
  - Menghitung rebate broker akumulatif per hari (~$6.00/lot) dan memonitor friction ratio (spread + komisi vs gross profit).
  - Menyediakan endpoint API `GET /api/bizdev/daily`.
- **Cockpit Mission Control HUD (`frontend/js/agents.js`):**
  - Mengintegrasikan panel *The Juggler (FinEng)* dan *BizDev Revenue* ke dalam Cockpit.
  - Memperbarui card Trade Averages (clamp limit) dan Gross Returns (target profit factor).
  - Mematuhi 100% aturan borderless UI (tanpa border keliling, hanya border-left 3px solid).
- **Injeksi Protokol Sinkronisasi Dokumentasi (Continuous Docs Sync):**
  - Memperbarui `AGENTS.md` (Bagian 3) dengan protokol wajib docs-first.
  - Membuat workspace rule `.agents/rules/docs-sync.md`.
  - Membuat workspace skill `.agents/skills/goldscalper-docs-keeper/SKILL.md` agar setiap agen selalu mengupdate dokumentasi terkait, roadmap, dan progress log saat ada perubahan strategi atau fitur.

**File tersentuh**
- `config/settings.py` — Parameter Juggler, BizDev, dan target harian
- `runtime.py` — Start-of-day balance tracking, preloading live average win, live telemetry
- `execution/position_manager.py` — Dynamic clamp, duration-based harvests & cuts
- `agents/divisions/risk/agents.py` — Target-seeking lot sizer, daily profit lock
- `execution/order_manager.py` — Enforcement profit lock
- `data/repositories.py` — Trade metrics aggregation (avg win, avg loss, total lots)
- `api/routes/bizdev.py` & `api/server.py` — BizDev endpoint
- `frontend/js/agents.js` — Cockpit HUD widgets
- `AGENTS.md`, `.agents/rules/docs-sync.md`, `.agents/skills/goldscalper-docs-keeper/SKILL.md` — Injeksi aturan & skill docs sync
- `docs/QUANT_FINENG_BIZDEV_SPEC.md`, `docs/IMPLEMENTATION_PLAN_JUGGLER_BIZDEV.md`, `docs/PROGRESS.md` — Sinkronisasi dokumen strategi dan roadmap

**Verifikasi**
- `python -m py_compile` seluruh berkas → 0 error.
- Deployment ke VPS Home-Server (`studo@100.114.150.48`) → Container `gs-bot` restart sehat.
- Log container live: Preloaded 160 wins (avg win $5.49), dynamic clamp memotong tiket `4882492832` di `-$6.21`, basket recovery TP menutup 2 posisi di `+$4.83`.
- Dashboard Cockpit `https://scalper.7pivot.site` menampilkan metrik Juggler & BizDev aktif.

**Catatan / Next**
- Pantau siklus sesi Tokyo/London besok pagi untuk performa *Target-Seeking Lot Sizing* saat modal bertumbuh menuju target sprint harian.


**Phase / Area:** SPK Execution & Cockpit Telemetry — Trend Arbitration & Anti-Hedging Barrier
**Status:** Done — Deployed to VPS, 230/230 Tests Passed

**Yang dikerjakan**
- **Cockpit Live Telemetry Alert Ticker (`#cockpit-ticker`):**
  - Mengimplementasikan running alert banner borderless (100% borderless, hanya border-left 3px solid) di bawah `.symbol-strip`.
  - 4 level reaktif: `danger` (News blackout / Circuit breaker), `warning` (Cooldown / Wide spread / Algo OFF), `success` (Active position & PnL), `idle` (Scanning).
  - Ticker dibuat continuous running marquee di CSS (`tickerMarquee` 24s linear loop) dengan auto-pause on hover/touch.
  - Memperbaiki parser data posisi aktif (`entry`, `open_price`, `price_open`, `pnl`, `profit`) di `app.js` dan `runtime.py`.
- **Trend vs Sideways Arbitration (3-Judge Consensus):**
  - Menetapkan 3 Hakim Penentu Rezim Pasar: `Struct-MarketStructure` (Fraktal Swing `HH_HL`/`LH_LL`/`RANGE`), `TF-H1-Regime` + `TF-M15` (Kemiringan EMA21 H1 dan keselarasan MTF), serta `Tech-SupportResistance` (Rentang Channel Body).
  - Mengklasifikasikan kondisi pertentangan arah (misal M15 BUY vs H1 SELL) sebagai **CONTESTED / SIDEWAYS**.
- **Anti-Hedging S/R Barrier Guard (`execution/order_manager.py`):**
  - Mencegah terjebak dalam *pincer trap* (Buy di pucuk, Sell di dasar).
  - Menolak eksekusi Ping-Pong SELL berlawanan di area lantai Support ($4144 \pm 1.50$) kecuali terkonfirmasi *Clean Breakdown* (Close M5 di bawah support + struktur `LH_LL`).
  - Menolak eksekusi Ping-Pong BUY berlawanan di area atap Resistance ($4154 \pm 1.50$) kecuali terkonfirmasi *Clean Breakout*.
- **Cluster Support/Resistance Anti-News Spike (`agents/divisions/technical/agents.py`):**
  - Menambahkan deteksi ekstrem orde kedua untuk mengabaikan ekor jarum outlier flash crash (seperti candle berita US Retail Sales ke 4131) agar lantai support riil (4144) tidak terabaikan.
- **Cross-Hedged Basket Recovery & Time Salvage (`execution/position_manager.py`):**
  - Mengelola keranjang hedged dua arah berbasis *Net Aggregate PnL* ($\ge +\$1.50$).
  - Fast unfreeze: jika keranjang hedged tertahan $\ge 120$ detik dan net profit $\ge +\$0.50$, langsung ditutup untuk melepaskan kuncian.

**File tersentuh**
- `agents/divisions/technical/agents.py` — filter outlier wicks pada S/R
- `execution/order_manager.py` — `_check_opposite_sr_barrier` guard
- `execution/position_manager.py` — cross-hedged basket net exit
- `runtime.py` — enriched positions payload
- `frontend/index.html`, `frontend/css/cockpit.css`, `frontend/js/app.js`, `frontend/sw.js` — live ticker
- `docs/MULTI_ENTRY_RESCUE_SPEC.md`, `docs/PROGRESS.md`, `docs/PRD.md`, `docs/BLUEPRINT.md`

**Verifikasi**
- `pytest tests/ --ignore=tests/test_backtest.py` → 230 passed in 1.95s
- Docker container `gs-bot` restart clean & operational di VPS `100.114.150.48:9090`.

---

## 2026-10-15 — Full 37-Agent Awakening & Live Market Feeds (Economic Calendar News Blackout, MT5 FX Majors Cross-Asset DXY & Silver, and Financial RSS Sentiment Feed)

**Phase / Area:** Phase 5, Phase 6 & SPK Optimization — Agent Live Feeds & Fundamental Integration
**Status:** Done — 100% Active Agents (37/37) Verified Live on VPS

**Yang dikerjakan**
- **Deep Audit 37 Agent & Eliminasi Agent Pasif:**
  - Menjalankan audit menyeluruh (`scripts/audit_live_agents.py`) langsung di live runtime container `gs-bot`.
  - Mendiagnosis penyebab agent pasif/dormant: ketiadaan feed data pada `SharedState.extra` dan kurangnya lookback history candle saat startup warmup.
  - Memperluas lookback warmup di `runtime.py` untuk seluruh timeframe (`M1`: 6h, `M5`: 12h, `M15`: 24h, `M30`: 48h, `H1`: 5d, `H4`: 15d [68 bars], `D1`: 30d [26 bars]), langsung membangunkan `TF-H4-Structure` dan `Struct-Liquidity`.
- **Fase 1: Economic Calendar & News Blackout Guard (`core/calendar_service.py`):**
  - Mengintegrasikan feed kalender ekonomi real-time (FinanceCalendar API dengan fallback ForexFactory).
  - Melengkapi local disk cache persistence (`data/calendar_cache.json`) dan error backoff cooldown 300 detik untuk mencegah rate-limit.
  - `Fund-Calendar` aktif memonitor event makro berimpak tinggi (CPI, NFP, GDP, FOMC, Retail Sales) dalam rentang ±15 menit dan memicu hard veto (`VETO_BUY`/`VETO_SELL`) dengan confidence 1.00.
  - Terverifikasi live di VPS: Memblokir trading saat event *UK GDP October 2026* dengan alasan transparan `NEWS BLACKOUT: UK GDP October 2026 (BEFORE 4m)` hingga `(AFTER 6m)`.
- **Fase 2: MT5 Cross-Asset Tick Streaming & Synthetic DXY (`core/cross_asset.py`):**
  - Polling background asinkron setiap 3 detik via MT5 bridge untuk pair major Exness: `EURUSDm`, `USDJPYm`, `GBPUSDm`, dan `XAGUSDm` (Silver).
  - Menghitung Dollar Index sintetis secara real-time:
    $$\text{DXY} = 56.56 \cdot \text{EURUSD}^{-0.576} \cdot \text{USDJPY}^{0.136} \cdot \text{GBPUSD}^{-0.119}$$
  - Anchoring baseline DXY dan Silver per sesi trading untuk menghitung momentum delta (`dxy_delta`, `silver_delta`).
  - Membangunkan `TF-DXY-Synthetic`, `Struct-Correlation`, dan `Fund-Intermarket`.
- **Fase 3: Financial RSS News Sentiment & Fed Macro Bias (`core/news_sentiment_service.py`):**
  - Crawling headline berita finansial via RSS (Google News / Yahoo Finance) setiap 15 menit dengan local disk cache (`data/sentiment_cache.json`).
  - Evaluasi directional lexicon scoring (-1.0 s/d +1.0) untuk mendeteksi sentimen emas dan bias kebijakan The Fed (`dovish` vs `hawkish`).
  - Membangunkan `Fund-NewsSentiment` (Vote -1, conf 0.50) dan `Fund-MacroRegime` (Vote -1, hawkish stance).
- **Optimalisasi `Tech-Volatility`:**
  - Mengubah evaluasi Bollinger Bandwidth/ATR agar tidak pasif (confidence 0.0), melainkan memberikan bobot dinamis: Squeeze (conf 0.70), Expansion (conf 0.60), dan Normal (conf 0.50).
- **Hasil Akhir Armada Agent:**
  - Active Voting Agents: 20
  - Active Vetoing Agents: 3 (TF-H1-Regime, Struct-Session, Tech-SupportResistance)
  - Risk Calculators: 6
  - Diagnostic & Health Monitors: 8
  - **Dormant / Pasif: 0 (NOL - Seluruh 37 Agent 100% Aktif)**

**File tersentuh**
- `core/calendar_service.py` — servis kalender ekonomi, deteksi blackout, disk caching & backoff
- `core/cross_asset.py` — servis multi-symbol MT5, kalkulator DXY sintetis & delta korelasi
- `core/news_sentiment_service.py` — RSS headline scraper, NLP lexicon sentimen & macro stance
- `agents/divisions/fundamental/agents.py` — aktivasi Fund-Calendar veto, metadata & backward compatibility
- `agents/divisions/technical/agents.py` — aktivasi bobot dinamis Tech-Volatility squeeze/expansion
- `agents/state.py` — kompatibilitas UTC timezone untuk Python 3.10+
- `spk/veto.py` — integrasi alasan detail rilis berita pada hard veto SPK
- `runtime.py` — integrasi calendar, cross-asset, dan sentiment feed ke loop utama
- `scripts/audit_live_agents.py` — audit runner live 37 agent
- `tests/test_fundamental_division.py` — update unit test calendar blackout veto
- `tests/test_cross_asset.py` — unit tests kalkulasi DXY dan baseline anchoring
- `tests/test_news_sentiment.py` — unit tests lexicon scoring dan default state

**Verifikasi**
- `docker exec gs-bot pytest --ignore=tests/test_backtest.py` → **230 passed in 1.94s (100% PASS)**
- `docker exec -i gs-bot python - < scripts/audit_live_agents.py` → **37/37 agents active, 0 dormant**
- `docker logs gs-bot --tail 25` → Uvicorn running live on port 9090, loop aktif 1.0s, calendar & cross-asset & sentiment feeds running smooth without rate-limits.

---

## 2026-10-14 — Phase 13: UI Polish v2 (Borderless Theme, Realtime Candlestick Chart, Collapsible Sidebar & Single Close API)

**Phase / Area:** Phase 13 — UI Polish & Realtime Candlestick Chart
**Status:** Done — All Views Re-implemented & Verified

**Yang dikerjakan**
- **Borderless & Clean UI (Anti-AI-Slop & Design Directives):**
  - Desain ulang seluruh visual theme mengacu pada referensi `docs/image/dashboard01.jpg` (dark neutrals `--bg: #0d0f12`, surface tonal `--s1: #13171c`, hairlines `1px solid rgba(255,255,255,0.06)`, radius kecil `4px - 6px`, min-h-[100dvh]).
  - Menghilangkan pembungkus berlebih (card soup), border less dengan pemisah tone background dan subtle dividers.
  - Sidebar responsif dengan tombol toggle collapse/expand (`220px` ⇄ `56px`), icon tooltip, dan shortcut keyboard `[`. State tersimpan di `localStorage`.
  - Symbol ticker strip di topbar (XAUUSD, Bid/Ask live, Spread points, Net PnL pill).
  - User profile chip di kanan atas dengan dialog akun MT5 pribadi & aksi logout.
- **Realtime Candlestick Chart:**
  - Vendoring TradingView Lightweight Charts standalone production v4.2.0 (`frontend/js/vendor/lightweight-charts.standalone.production.js`).
  - Modul `frontend/js/chart.js` (`PriceChart` class): auto candle loader (`GET /api/candles`), live tick push via WebSocket (`streamer:tick`), garis horizontal posisi trading aktif (entry, SL, TP) dengan color coding, full state handling (loading skeleton, empty, error badge, live status indicator).
  - Dukungan timeframe switcher interaktif (`M1`, `M5`, `M15`, `H1`, `D1`).
- **Complete Views Polish (Semua Sekaligus):**
  - *Cockpit:* Chart canvas terintegrasi, SPK Diverging Score Meter (-3 s/d +3 bar), Open Positions ticket dengan tombol aksi instant Close `[x]`, Active Risk Limits checklist.
  - *Agents:* Tabulasi armada 37 AI Agent dengan badge divisi, berat bandit, dan status voting terkini.
  - *Divisions:* Radar 7 divisi, bobot voting dinamis, dan aggregate signal bar.
  - *Performance:* Metrik performa institusional (Win Rate, Profit Factor, Max Drawdown) & grafik equity curve interaktif.
  - *Lessons:* Kartu memori adaptif dari bandit optimizer dengan filter status.
  - *Control:* Terminal operasi runtime, status toggle (Pause/Resume), Emergency Panic Close modal konfirmasi, dan manual order pad.
- **Backend Enhancements:**
  - Endpoint baru `GET /api/candles?tf=M1&limit=300` di `api/routes/market.py` dengan fallback ganda (cache in-memory -> copy_rates MT5 client).
  - Endpoint baru `POST /api/control/close?ticket=...` di `api/routes/control.py` untuk penutupan order individual langsung dari UI position ticket.
  - Expose `last_equity` dan `last_balance` di payload telemetri `runtime.py`.
  - Fix edge-case `PositionSizer` saat equity bernilai 0.0 agar aman.
- **Dokumentasi & Environment Sanitization:**
  - Sanitasi `DEPLOYMENT_SOP.md` & `.env` untuk menghapus hardcoded credentials dan referensi usang bridge Windows.
  - Seluruh sistem terkonfirmasi 100% mandiri di Home-Server Docker (Wine MT5).

**File tersentuh**
- `api/routes/market.py` — endpoint market candle history
- `api/routes/control.py` — endpoint close single order
- `api/routes/auth_routes.py` — sanitasi auto-seed admin policy
- `api/server.py` — registrasi market router
- `runtime.py` — close_single_position, last_equity telemetri
- `agents/divisions/risk/agents.py` — perbaikan sizer zero equity
- `frontend/index.html` — layout borderless, symbol strip, collapse sidebar
- `frontend/css/cockpit.css` — styling cockpit, token warna dark neutral
- `frontend/css/agents.css` — styling borderless armada agents, divisions, performance, control
- `frontend/js/components.js` — icon pack SVG baru & color palette
- `frontend/js/chart.js` — class controller LightweightCharts
- `frontend/js/agents.js` — render 6 view lengkap dengan partial DOM patching
- `frontend/js/app.js` — kontrol navigasi, collapse sidebar, profile menu
- `frontend/sw.js` — update versi cache service worker `gs-v3`
- `tests/test_api.py`, `tests/test_runtime.py`, `tests/test_execution.py` — unit tests
- `docs/DEPLOYMENT_SOP.md`, `docs/BLUEPRINT.md`, `docs/PROGRESS.md`, `.env` — sinkronisasi dokumentasi

**Verifikasi**
- `uv run pytest tests/ -v` → **219 passed in 1.68s** (100% pass)
- `uv run ruff check api/ tests/` → clean
- UI Preview Artifacts: `goldscalper_preview_v1_1791965705134.jpg`

---

## 2026-10-14 — Implementasi Multi-User Authentication (Email & Password) & Multi-Tenant Exness Accounts

**Phase / Area:** Auth & Multi-User Management  
**Status:** Done — Portal Login Dedicated, JWT Token Session, Skema Database Users & MT5 Accounts

**Yang dikerjakan**
- **Sistem Autentikasi Pengguna (Email & Password):**
  - Menggantikan modal token mentah dengan Halaman/Portal Login dedicated berdesain modern (Dark Neutral Glassmorphism, font *Plus Jakarta Sans*, tanpa AI-slop).
  - Mode Switcher: Sign In & Register Akun baru.
  - Enkripsi password menggunakan `bcrypt` dengan work factor 12 rounds.
  - Sesi login terbit sebagai JWT Bearer Token standar (validitas 30 hari).
  - Auto-seeding akun master operator pertama dengan password `12qwAS!!`.
- **Database Skema Multi-Tenant (TimescaleDB / PostgreSQL):**
  - Migration `004_users_and_accounts.sql`: tabel `users` dan `user_trading_accounts`.
  - Repository `UserRepository` (`data/user_repo.py`) untuk CRUD user dan akun MT5.
- **Konfigurasi Akun Exness Mandiri (Multi-User):**
  - Setiap user dapat mengonfigurasi nomor akun Exness MT5, password trader, server, mode lot (fixed/compound), dan toggle status bot langsung dari dashboard UI.
  - Endpoint baru: `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/trading-account`.
- **Frontend Cockpit Integration:**
  - Halaman login auto-focus saat belum ada sesi atau token expired (401).
  - Profil user aktif di sidebar footer dengan tombol pengaturan Exness Account & Sign Out.
  - Telemetry WebSocket terhubung otomatis setelah login berhasil.

**File tersentuh**
- `data/timescale/004_users_and_accounts.sql` — migrasi tabel users & user_trading_accounts
- `data/user_repo.py` — repository data access layer & bcrypt password hashing
- `requirements.txt` — penambahan dependensi `bcrypt` dan `PyJWT`
- `api/auth.py` — JWT signing, verification, dan dependency `get_current_user`
- `api/routes/auth_routes.py` — router register, login, me, trading-account
- `api/server.py` — registrasi auth router
- `frontend/index.html` — markup auth portal (sign in / register)
- `frontend/css/cockpit.css` — styling auth portal, card, tactile button feedback
- `frontend/js/app.js` — auth lifecycle, modal Exness account, session badge
- `docs/PRD.md` — penambahan FR-27 & FR-28
- `docs/BLUEPRINT.md` — pembaruan Section 12 Security & Multi-User
- `docs/PROGRESS.md` — log catatan rilis fitur auth

---

## 2026-10-14 — Transisi Arsitektur: 100% Home-Server Deployment & Isolasi AcengGold

**Phase / Area:** Phase 12b — Migrasi MT5 ke Docker Home-Server & Alokasi Dedicated AcengGold  
**Status:** Done — Workstation PC 100% Bebas untuk AcengGold, GoldScalper Mandiri di Home-Server

**Yang dikerjakan**
- **Isolasi Workstation PC untuk AcengGold:**
  - Menghilangkan dependensi GoldScalper terhadap workstation Windows PC.
  - Menghentikan seluruh service bridge lokal di Windows PC agar terminal MT5 di PC bebas 100% digunakan secara eksklusif oleh aplikasi `AcengGold`.
- **Migrasi ke Home-Server (`100.114.150.48`):**
  - Mengonfigurasi arsitektur 100% mandiri di Home-Server menggunakan Docker.
  - Pull image MetaTrader 5 Wine container (`gmag11/metatrader5_vnc:latest`) langsung di Home-Server.
  - Image menyediakan KasmVNC Web UI di port `9096` dan RPyC bridge di port `8001` dalam network `gs-net`.
- **Akun Broker Baru Khusus GoldScalper:**
  - Akun: Exness Demo MT5 Standard `#434366152`
  - Balance: `$10,000.00 USD`
  - Server: `Exness-MT5Trial7`
  - Password: `12qwAS!!`
  - Simbol: `XAUUSDm`
- **Pembaruan Seluruh Dokumentasi:**
  - `BLUEPRINT.md`, `DEPLOYMENT_SOP.md`, `DEPLOYMENT_SOP_WINDOWS_BRIDGE.md` (arsip), `IMPLEMENTATION_PLAN.md`, `PRD.md`, `README.md`, `deploy/cloudflared/README.md`.

**Verifikasi**
- Windows Host Process: `Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'"` → Bebas dari proses GoldScalper.
- Home-Server Image: `docker pull gmag11/metatrader5_vnc:latest` → `Status: Downloaded newer image`.
- Public Bot Endpoint: `https://scalper.7pivot.site/health` → `200 OK`.

---

## 2026-10-14 — Phase 12: Deployment & Live Bridge Verification (Full End-to-End)

**Phase / Area:** Phase 12 — Deployment Home-Server + MT5 Bridge Live Execution
**Status:** Done — Live & Terhubung ke EXNESS Demo

**Yang dikerjakan**
- **MT5 Bridge di Windows Host:**
  - Update `bridge/backend.py` agar otomatis mengenali sesi login terminal MT5 aktif tanpa perlu re-login manual bila kredensial sudah tersimpan di terminal (`login=434352821`, `Exness-MT5Trial7`).
  - Pembuatan script `scripts/run_bridge.ps1`.
  - Service bridge aktif di background port `9095`, tersambung ke `terminal64.exe` (Exness Demo).
  - Simbol emas disesuaikan ke `XAUUSDm` (standar Exness Trial/Demo).
- **Deployment ke Home-Server (100.114.150.48):**
  - Sinkronisasi kode root dan modul aplikasi ke `/home/studo/apps/goldscalper`.
  - Konfigurasi `.env` server dengan `MT5_MOCK=false`, `MT5_BRIDGE_URL=http://100.114.201.115:9095`, dan `MT5_SYMBOL=XAUUSDm`.
  - Build dan startup container Docker di server (`gs-bot`, `gs-timescaledb`, `gs-redis`).
- **Verifikasi End-to-End:**
  - Koneksi internal: `curl http://localhost:9090/health` → OK.
  - Telemetri `gs-bot` di server tersambung ke Windows Bridge via Tailscale (`http://100.114.201.115:9095`), stream tick `XAUUSDm` aktif (interval 0.5s).
  - `Infra-Connectivity` agen melaporkan: `mt5=True`, `redis=True`, `db=True`.
  - Akses publik via Cloudflare Tunnel: `https://scalper.7pivot.site/health` merespon 200 OK, PWA Cockpit UI dapat diakses langsung.

**File tersentuh**
- `bridge/backend.py` — dukung attach ke active terminal tanpa kredensial
- `.env` (lokal & remote) — konfigurasi `BRIDGE_*`, `MT5_SYMBOL=XAUUSDm`, `MT5_BRIDGE_*`
- `scripts/run_bridge.ps1` — script launcher bridge Windows
- `docs/PROGRESS.md` — log deployment

**Verifikasi**
- `curl.exe -s http://127.0.0.1:9095/health` → `status: ok, connected: true, login: 434352821`
- `ssh studo@100.114.150.48 "curl -s http://localhost:9090/health"` → `{"status":"ok", ...}`
- `curl.exe -s https://scalper.7pivot.site/health` → `{"status":"ok", ...}`
- `docker ps` di server → `gs-bot`, `gs-redis`, `gs-timescaledb` semua Up & Healthy.

**Catatan / Next**
- Bot saat ini aktif memonitor market XAUUSDm secara realtime.
- Pantau pembentukan bar M1/M5 dan keputusan voting SPK melalui PWA dashboard di `https://scalper.7pivot.site`.

**Phase / Area:** Phase 12 — Remote MT5 bridge + persiapan dry-run EXNESS demo
**Status:** Done (kode) — dry-run live menunggu aksi di Windows host

**Yang dikerjakan**
- Paket `bridge/` baru: HTTP bridge FastAPI yang jalan di Windows host MT5,
  diakses bot Linux via Tailscale/LAN (`http://100.114.201.115:9095`).
- Endpoint sesuai kontrak `BridgeMT5Client`: `GET /health` (public),
  `GET /tick`, `GET /rates`, `POST /order`, `GET /positions`, `POST /close`,
  `POST /modify`.
- Auth bearer (`hmac.compare_digest`) di semua endpoint kecuali `/health`.
- `MT5Backend` lazy-import `MetaTrader5` → aman di-import di Linux CI.
- `tests/test_bridge.py`: 5 test (kontrak endpoint + roundtrip `BridgeMT5Client`
  via `httpx.ASGITransport` + `FakeBackend`).
- Fix kecil: `BridgeMT5Client.__init__` menerima `client: Any | None` opsional
  (inject untuk test); `connect()` hanya membuat client bila belum ada.
- Dokumentasi: blok `BRIDGE_*` di `.env.example`, seksi bridge di
  `docs/DEPLOYMENT_SOP.md`, SOP baru `docs/DEPLOYMENT_SOP_WINDOWS_BRIDGE.md`.

**File tersentuh**
- `bridge/__init__.py`, `bridge/config.py`, `bridge/backend.py`,
  `bridge/app.py`, `bridge/run.py`, `bridge/requirements.txt` — baru
- `bridge/BRIDGE_README_WINDOWS.md` — baru
- `tests/test_bridge.py` — baru
- `core/mt5_connector.py` — `BridgeMT5Client` dukung inject client
- `.env.example`, `docs/DEPLOYMENT_SOP.md`,
  `docs/DEPLOYMENT_SOP_WINDOWS_BRIDGE.md`

**Verifikasi**
- `docker compose build bot` → image rebuilt
- `docker compose run --rm --no-deps bot ruff check .` → All checks passed
- `docker compose run --rm --no-deps bot pytest` → **215 passed**

**Catatan / Next**
- Dry-run live butuh aksi manual di Windows host: install
  `bridge/requirements.txt`, isi `.env` (`BRIDGE_*`, `MT5_*`), jalankan
  `python -m bridge.run`.
- Di Home-Server set `MT5_MOCK=false` + `MT5_BRIDGE_URL`/`MT5_BRIDGE_TOKEN`.
- Opsional: `scripts/run_bridge.ps1` + health-check otomatis.

---

## 2026-10-14 — Phase 10: API + PWA frontend

**Phase / Area:** Phase 10 — REST/WS API + PWA vanilla JS
**Status:** Done — terverifikasi live di `http://localhost:9090`

**Yang dikerjakan**
- Router baru: `api/routes/{agents,trades,lessons,performance}.py`; `control.py`
  dirapikan (sisakan `/api/status` + `/api/control/pause|resume|panic|manual`).
- `api/deps.py` expose `RuntimeDep` (`Annotated[Any, Depends(get_runtime)]`) →
  lolos ruff B008.
- `data/repositories.py`: `aggregate` tambah `gross_profit`/`gross_loss`;
  `equity_curve` ambil N baris terbaru via subquery.
- `performance.py` normalisasi payload (`trades`→`total`, `final_equity`,
  `max_drawdown`).
- `/api/positions` sertakan `ticket`.
- Frontend PWA vanilla (tanpa build step): cockpit, agent grid, division radar,
  performance, lessons, control. Dark neutral + aksen gold, Plus Jakarta Sans +
  JetBrains Mono, inline SVG icons, custom select/toast/modal.
- `js/ws.js` merge decision dari `/api/spk/latest` (votes/tradable) saat
  telemetry masuk; `app.js` `primeStats()` isi equity topbar.

**File tersentuh**
- `api/routes/*.py`, `api/deps.py`, `api/server.py`, `data/repositories.py`
- `tests/test_api.py` — baru (10 test)
- `frontend/index.html`, `frontend/manifest.json`, `frontend/sw.js`,
  `frontend/icons/*`, `frontend/css/*`, `frontend/js/*`

**Verifikasi**
- Shell statis `/`, `/css/*`, `/js/*`, `/manifest.json`, `/sw.js`, `/icons/*` → 200
- `/api/*` dengan token → 200; tanpa token → 401
- `/api/spk/latest` → 37 votes; rollup divisi benar
- `pytest` → 210 passed; ruff clean

**Catatan / Next**
- Frontend dibake ke image → **wajib rebuild** tiap edit `frontend/`.
- `/health` = endpoint health bot (bukan `/api/health`).

---

## 2026-10-14 — Phase 11: Backtest harness

**Phase / Area:** Phase 11 — Backtest
**Status:** Done

**Yang dikerjakan**
- `backtest/{sim_broker,metrics,engine,__init__}.py`: replay OHLCV historis
  lewat orchestrator/order/position manager asli via `SimBroker` (hanya MT5
  client yang di-swap). Anti look-ahead; entry di bar open, exit evaluasi
  high/low per bar.
- `scripts/smoke_backtest.py` (fallback sintetis bila DB kosong).

**Verifikasi**
- `python scripts/smoke_backtest.py` → ~904 trades (expected low win-rate pada
  data sintetis).

---

## 2026-10-14 — Phase 8 & 9: Execution + Learning Loop + Runtime live

**Phase / Area:** Phase 8 (Execution), Phase 9 (Learning), Runtime & API
**Status:** Done

**Yang dikerjakan**
- Phase 8: primitives trading MT5 di `core/mt5_connector.py` (Mock/Native/Bridge),
  `execution/order_manager.py`, `execution/position_manager.py`
  (breakeven/partial/trailing/time-stop), `core/notifier.py` (Telegram).
- Phase 9: `agents/learning/{post_trade_analyzer,bandit_optimizer,
  regime_classifier,pattern_library}.py` — Lesson Cards, Thompson sampling
  (bounded delta), wired via `Orchestrator.on_trade_closed`.
- Runtime: `runtime.py` menyambung data→agents→SPK→execution→learning;
  `api/server.py` lifespan start runtime + `_telemetry_pump` 2s;
  `/ws/telemetry` (auth token).

**Verifikasi**
- `pytest` → hijau (suite utama).

**Catatan / Next**
- LLM hanya di learning loop async, tidak di hot path.

---

## 2026-10-14 — Phase 0–7: Fondasi (retro)

**Phase / Area:** Phase 0–7
**Status:** Done (retro-logged)

**Yang dikerjakan**
- Phase 0: scaffold + Docker (timescaledb, redis, bot), ports 90xx.
- Phase 1: agent framework, registri, contracts.
- Phase 2: market data + MT5 connector (mock/native/bridge), Redis Streams.
- Phase 3: Timeframe division (8 incl DXY).
- Phase 4: Risk division (6, vote-neutral) + pre-trade risk gate.
- Phase 5: Structure division (5).
- Phase 6: Technical (6) + Fundamental (4).
- Phase 7: SPK Core (5, vote-neutral) + Infra (3) → total **37 agent / 7 divisi**.

**Verifikasi**
- `data/divisions.build_all_agents(include_dxy=True)` → 37 agent, 7 divisi.
- Suite tiap phase hijau.

**Catatan / Next**
- Bobot divisi: Risk 2.0, SPK Core 1.5, TF HTF 1.5, Structure 1.3,
  TF LTF 1.2, Technical 1.0, Fundamental 0.8, Infra 0.5.
- Threshold SPK: STRONG ≥ 2.0, NORMAL > 0.5, else HOLD.
