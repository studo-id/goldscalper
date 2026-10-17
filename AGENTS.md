# GoldScalper Project Directive: Strict Borderless UI Architecture & Theme

> **STATUS: HUKUM SISTEM MUTLAK (MUTU TINGGI - ANTI AI-SLOP)**
> Berlaku untuk seluruh AI Agent, pair programmer, subagent, dan setiap berkas antarmuka pengguna (HTML, JS, CSS, TS) di proyek GoldScalper.

---

## 🚫 1. ATURAN MUTLAK BORDERLESS (NON-NEGOTIABLE)

1. **100% BORDERLESS:**
   - DILARANG KERAS memberikan `border` keliling (`1px solid`, `border-white/10`, `border-neutral-800`, dsb.) pada:
     - Card / Panel / Containers
     - Toolbar / Filter Bar / Headers
     - Badges / Segmented Controls / Pills / Tabs
     - Buttons / Inputs / Dropdowns / Datepickers
     - Tooltips / Modals / Overlays
   - Gunakan `border: none !important;` atau `border: 0;` secara konsisten di seluruh komponen.

2. **SATU-SATUNYA PENGECUALIAN:**
   - **Border Kiri Status Indicator Strip:**
     - Profit / Win: `border-left: 3px solid #10b981 !important;`
     - Loss: `border-left: 3px solid #ef4444 !important;`
     - Standby / Neutral: `border-left: 3px solid #64748b !important;`
   - Selain indikator sisi kiri ini, SEMUA sisi (atas, kanan, bawah) WAJIB `border: none`!

---

## 🎨 2. SISTEM ELEVASI & PEMISAHAN DATA (TONAL HIERARCHY)

Pemisahan grup data, kartu, dan komponen WAJIB menggunakan kontras tonal murni dan whitespace, BUKAN border garis AI-slop:

1. **Token Permukaan Gelap (Dark Surface Palette):**
   - `--bg`: `#0b0e14` (Latar belakang utama aplikasi)
   - `--s1`: `#11151c` (Surface card / panel / toolbar level 1)
   - `--s2`: `#161b24` (Surface recessed / segmented pill track / input background)
   - `--s3`: `#1c2330` (Surface hover / active track)

2. **Aksen & State Indikator:**
   - **Gold Accent:** `#d9a441` (`var(--accent)`)
   - **Pill Aktif:** `background: var(--accent); color: #0b0e14; font-weight: 700; border: none;`
   - **Win / Up:** `#10b981` / `#36c98d` (`var(--up)`)
   - **Loss / Down:** `#ef4444` / `#ef5f6b` (`var(--down)`)
   - **Warning / Flat:** `#f59e0b` (`var(--warn)`)

3. **Tipografi & Numerik:**
   - Teks Utama / UI: `Plus Jakarta Sans`
   - Angka / Metrik / Finansial / PnL: `JetBrains Mono` (`font-variant-numeric: tabular-nums;`)

---

## 📚 3. PROTOKOL WAJIB SINKRONISASI DOKUMENTASI (NON-NEGOTIABLE)

Setiap AI Agent, pair programmer, atau subagent yang bekerja di proyek GoldScalper **WAJIB HUKUMNYA** mematuhi aturan dokumentasi berikut:

1. **Selalu Update Dokumentasi Terkait (Docs-First & Continuous Sync):**
   - Setiap kali terjadi perubahan strategi trading (SL/TP, dynamic bleeding clamp, sizer, timeframe, bobot voting), fitur baru, atau refaktor arsitektur, berkas dokumentasi di folder `docs/` **WAJIB diupdate secara bersamaan dalam siklus commit/deploy yang sama**.
   - DILARANG KERAS melakukan perubahan kode/parameter tanpa memperbarui dokumen spesifikasi induknya:
     - Log Progress & Worklog Kronologis ➔ [docs/PROGRESS.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/PROGRESS.md) *(Wajib ditambahkan entry baru untuk setiap fitur/kemajuan)*
     - Strategi FinEng / Juggler / BizDev ➔ [docs/QUANT_FINENG_BIZDEV_SPEC.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/QUANT_FINENG_BIZDEV_SPEC.md)
     - Perubahan Task / Roadmap ➔ [docs/IMPLEMENTATION_PLAN_JUGGLER_BIZDEV.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/IMPLEMENTATION_PLAN_JUGGLER_BIZDEV.md)
     - Arsitektur / Komponen / Port ➔ [docs/BLUEPRINT.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/BLUEPRINT.md)
     - Multi-Entry / Basket Rescue ➔ [docs/MULTI_ENTRY_RESCUE_SPEC.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/MULTI_ENTRY_RESCUE_SPEC.md)
     - Target / Scope Produk ➔ [docs/PRD.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/PRD.md)

2. **Pencatatan Progress Nyata (Changelog & Milestone Sync):**
   - Setiap penyelesaian tugas (task completed) wajib dicatat statusnya di Implementation Plan dan ditambahkan ke bagian teratas [docs/PROGRESS.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/PROGRESS.md).
   - Dokumen tidak boleh usang (*stale*). Parameter default di kode (`settings.py`, `.env.example`) harus sama persis dengan tabel spesifikasi di dokumentasi.

3. **Integritas Link & Indeks:**
   - Semua berkas dokumen baru wajib diindeks ke dalam `docs/BLUEPRINT.md` dan `docs/PRD.md` sebagai companion documents resmi.
   - Sinkronisasi server: Setiap kali deploy kode ke server, file dokumentasi juga wajib dikirim ke server via scp/rsync agar environment server selalu mencerminkan state dokumentasi terbaru.

---

## 🎯 4. HUKUM SISTEM STRATEGI TRADING: WAJIB MENGACU PORTFOLIO & TARGET HARIAN (THE JUGGLER DIRECTIVE)

Setiap AI Agent, pair programmer, atau subagent yang mereview, mengusulkan, atau memodifikasi logika strategi trading (entry, sizing, SL/TP, cutloss, multi-entry layering, pyramiding, hingga exit) **WAJIB SECARA DEFAULT DAN MUTLAK** mendasarkan keputusannya pada **3 Pilar Portfolio & Target Harian**:

1. **Portfolio Health State (Kesehatan Ekuitas Harian):**
   - **`DEFENSE` Mode (`daily_pnl_pct < 0%`):**
     - Sizing lot wajib mengecil (0.02–0.04 lot).
     - Pyramiding **DILARANG KERAS**.
     - Multi-entry layering dibatasi ketat (jarak minimum $\ge 30-35$ pips; jika drawdown $\le -4\%$, multi-entry dimatikan total).
     - Konsensus SPK wajib diperketat (gradient penalti s/d +60% untuk mengeliminasi noise single-agent).
   - **`GROWTH` Mode (`daily_pnl_pct \ge +3%`):**
     - Sizing lot boleh diperbesar secara proporsional menggunakan keuntungan pasar (*house money*).
     - Pyramiding hanya diizinkan jika posisi awal **sudah floating profit**.
   - **`BALANCED` Mode (`0% \le daily_pnl_pct < 3%`):** Beroperasi pada parameter baseline standar.

2. **Daily Sprint Target Proximity (Kedekatan Garis Finish):**
   - **Finish Line Lockdown (`remaining_target_usd \le $20`):**
     - Multi-entry / averaging / pyramiding **DITUTUP TOTAL** (hanya 1 single position).
     - Ambang batas SPK dinaikkan (`weak_threshold * 1.10 - 1.35`) untuk menolak trade marjinal.
   - **Target Achieved / Locked (`daily_profit_locked == True` atau `remaining_target \le $0`):**
     - SPK wajib mengembalikan `ACTION_HOLD` dan Veto Engine wajib mengaktifkan Hard Veto `daily_profit_locked`. Dilarang membuka trade baru.

3. **Dynamic Payoff Clamping:**
   - Dilarang keras menggunakan cut loss atau take profit statik/hardcoded yang mengabaikan performa hari ini.
   - Ambang cut loss dinamis wajib terikat pada performa kemenangan riil: `base_clamp = max(7.0, live_avg_win * 1.1) * health_mult`.
   - Take profit harus mengakomodasi runner $\ge \$7.50$ (atau $1.25\times \text{avg win}$) dengan pengunci modal *Early Break-Even* di $+25$ pips ($+\$2.50$).


