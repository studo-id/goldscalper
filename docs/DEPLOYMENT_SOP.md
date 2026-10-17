# Standard Operating Procedure (SOP) Deployment — GoldScalper

**Document Version:** 1.0  
**Effective Date:** 2026-10-14  
**Author:** AI Pair Programmer & Dev Team  
**Companion Documents:**  
- [BLUEPRINT.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/BLUEPRINT.md) (Architecture & Ports)  
- [PRD.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/PRD.md) (System Requirements)  
- [IMPLEMENTATION_PLAN.md](file:///c:/Users/STUDO/Documents/Project/APPS/trading/GoldScalper/docs/IMPLEMENTATION_PLAN.md) (Milestones & Tasks)  

---

## 1. Ringkasan Arsitektur & Lingkungan

Sistem GoldScalper kini beroperasi **100% mandiri di Home-Server (`studo@100.114.150.48`)**. Workstation Windows PC dialokasikan **khusus untuk aplikasi `AcengGold`** dan sama sekali tidak digunakan atau disentuh oleh GoldScalper.

| Komponen | Host | Deskripsi & Port |
|---|---|---|
| **GoldScalper Core & 37 AI Agents** | **Home-Server** (`studo@100.114.150.48`) | Docker container `gs-bot:9090` |
| **TimescaleDB (PostgreSQL 16)** | **Home-Server** (`studo@100.114.150.48`) | Docker container `gs-timescaledb:5433` |
| **Redis Cache & Pub/Sub** | **Home-Server** (`studo@100.114.150.48`) | Docker container `gs-redis:6380` |
| **MetaTrader 5 Runner (Wine)** | **Home-Server** (`studo@100.114.150.48`) | Docker container `gs-mt5:9096` (VNC UI) & `8001` (RPyC/Bridge) |
| **Cloudflare Tunnel** | **Home-Server** (`9router_tunnel`) | Container `cloudflared` eksisting milik stack `9router` |
| **Domain Publik** | **Cloudflare Zero Trust** | `https://scalper.7pivot.site` ➔ `http://host.docker.internal:9090` |
| **Windows PC Workstation** | **Windows PC** (`100.114.201.115`) | **Dedicated 100% untuk AcengGold** (Bebas total dari GoldScalper) |

```
                       Internet (Mobile Browser / PWA)
                                     │
                                     ▼
                        [Cloudflare Zero Trust]
                         `scalper.7pivot.site`
                                     │ (Tunnel)
                                     ▼
        ┌────────────────────────────────────────────────────────┐
        │       HOME-SERVER (100% Self-Contained Docker)         │
        │                                                        │
        │   9router_tunnel ──► host.docker.internal:9090         │
        │                             │                          │
        │                             ▼                          │
        │                      ┌─────────────┐                   │
        │                      │ gs-bot:9090 │                   │
        │                      └──────┬──────┘                   │
        │            ┌────────────────┼────────────────┐         │
        │            ▼                ▼                ▼         │
        │    timescaledb:5433    redis:6380       gs-mt5 (Wine)  │
        │                                         ├─ VNC: 9096   │
        │                                         └─ RPyC: 8001  │
        └────────────────────────────────────────────────────────┘
```

---

## 2. Alokasi Port Server (Aturan Anti-Tabrakan)

Server ini menampung beberapa aplikasi sekaligus. Pastikan port GoldScalper tidak bersinggungan:

* `20128` — 9router (Eksisting)
* `8787` — Headroom (Eksisting)
* `22000` / `22001` — AgencyHUB (Eksisting)
* **`9090`** — **GoldScalper FastAPI + WebSocket (gs-bot)**
* **`5433`** — **GoldScalper TimescaleDB (gs-timescaledb)**
* **`6380`** — **GoldScalper Redis (gs-redis)**
* **`9096`** — **GoldScalper MetaTrader 5 KasmVNC Web UI (gs-mt5)**
* **`8001`** — **GoldScalper MetaTrader 5 RPyC Bridge Port (Internal)**

---

## 3. Prasyarat Deployment (Prerequisites)

Sebelum memulai proses deploy, pastikan hal-hal berikut aktif:

1. **Tailscale VPN** aktif di Windows PC dan Home-Server.
2. Tes koneksi SSH ke Home-Server:
   ```powershell
   ssh studo@100.114.150.48 "hostname"
   ```
   *(Harus menghasilkan nama host home-server tanpa error jaringan).*
3. **Cloudflare Route** sudah dibuat di Tunnel `9router`:
   * **Hostname:** `scalper.7pivot.site`
   * **Service:** `HTTP` ➔ `host.docker.internal:9090`

---

## 4. Langkah-Langkah Deployment (Step-by-Step SOP)

### Langkah 1: Persiapan Direktori di Home-Server
Buka PowerShell di Windows PC, lalu buat direktori aplikasi di server:
```powershell
ssh studo@100.114.150.48 "mkdir -p /home/studo/apps/goldscalper"
```

### Langkah 2: Sinkronisasi Kode & File Konfigurasi
Unggah source code dan konfigurasi ke Home-Server (abaikan direktori lokal seperti `__pycache__`, `.venv`, `.git`):

```powershell
# Berpindah ke root direktori GoldScalper
cd C:\Users\STUDO\Documents\Project\APPS\trading\GoldScalper

# 1. Upload konfigurasi root
scp docker-compose.yml Dockerfile requirements.txt run.py pyproject.toml studo@100.114.150.48:/home/studo/apps/goldscalper/

# 2. Upload modul aplikasi
scp -r api config core agents spk execution data frontend scripts studo@100.114.150.48:/home/studo/apps/goldscalper/
```

### Langkah 3: Konfigurasi File Environment Server (`.env`)
Di server, siapkan file `.env`:
```powershell
# Buat/edit .env di server
ssh studo@100.114.150.48 "nano /home/studo/apps/goldscalper/.env"
```

Pastikan nilai berikut disesuaikan (sesuai template `.env`):
```env
APP_NAME=GoldScalper
ENVIRONMENT=production
DEBUG=false

HOST=0.0.0.0
PORT=9090
API_TOKEN=<generate_random_secret_string>
CORS_ORIGINS=https://scalper.7pivot.site,http://localhost:9090

# Database internal Docker
DB_HOST=timescaledb
DB_PORT=5432
DB_USER=goldscalper
DB_PASSWORD=<password_db_aman>
DB_NAME=goldscalper
POSTGRES_USER=goldscalper
POSTGRES_PASSWORD=<password_db_aman>
POSTGRES_DB=goldscalper

# Redis internal Docker
REDIS_HOST=redis
REDIS_PORT=6380
REDIS_DB=0

# MT5 Runner di Home-Server (Wine Docker Container)
MT5_MOCK=false
MT5_SYMBOL=XAUUSDm
MT5_LOGIN=434366152
MT5_PASSWORD=<password_trading_mt5>
MT5_SERVER=Exness-MT5Trial7

# Windows Bridge: TIDAK DIGUNAKAN (GoldScalper 100% mandiri di Home-Server Docker)
MT5_BRIDGE_URL=
MT5_BRIDGE_TOKEN=

RUN_MIGRATIONS=true
```

### Langkah 4: Build & Jalankan Container
Jalankan docker compose di server:
```powershell
ssh -t studo@100.114.150.48 "cd /home/studo/apps/goldscalper && sudo docker compose up -d --build"
```

### Langkah 5: Verifikasi Status Service
Periksa status kontainer:
```powershell
ssh studo@100.114.150.48 "sudo docker ps --filter 'name=gs-'"
```

Pastikan output menampilkan container berstatus **Up (healthy)**:
- `gs-bot` (port `0.0.0.0:9090->9090/tcp`)
- `gs-redis` (port `0.0.0.0:6380->6380/tcp`)
- `gs-timescaledb` (port `0.0.0.0:5433->5432/tcp`)
- `gs-mt5` (port `0.0.0.0:9096->9096/tcp` untuk KasmVNC Web UI & `8001` untuk internal RPyC)

---

## 5. Prosedur Uji Kelayakan (Sanity & Health Check)

Lakukan tes bertingkat dari internal hingga akses internet publik:

### 1. Tes Akses Internal Server (Localhost)
```powershell
ssh studo@100.114.150.48 "curl -s http://localhost:9090/health"
```
*Ekspektasi respon:* `{"status":"ok",...}` atau HTTP 200.

### 2. Tes Akses Origin via `host.docker.internal` dari `9router_tunnel`
Pastikan container tunnel 9router bisa menjangkau port 9090 host:
```powershell
ssh studo@100.114.150.48 "sudo docker exec 9router_tunnel curl -s http://host.docker.internal:9090/health"
```

### 3. Tes Domain Publik Cloudflare
Buka terminal Windows atau browser:
```powershell
curl -I https://scalper.7pivot.site/health
```
*Ekspektasi respon:*
```http
HTTP/1.1 200 OK
Server: cloudflare
...
```

---

## 6. Prosedur Maintenance & Troubleshooting

### Memantau Log Realtime
```powershell
# Log Bot Engine & API
ssh -t studo@100.114.150.48 "cd /home/studo/apps/goldscalper && sudo docker compose logs -f bot"

# Log Database TimescaleDB
ssh -t studo@100.114.150.48 "cd /home/studo/apps/goldscalper && sudo docker compose logs -f timescaledb"

# Log Redis Stream Bus
ssh -t studo@100.114.150.48 "cd /home/studo/apps/goldscalper && sudo docker compose logs -f redis"

# Log MT5 Wine Container
ssh -t studo@100.114.150.48 "cd /home/studo/apps/goldscalper && sudo docker compose logs -f mt5"
```

### Restart Service Tertentu
```powershell
# Restart bot saja (tanpa mematikan DB/Redis/MT5)
ssh studo@100.114.150.48 "cd /home/studo/apps/goldscalper && sudo docker compose restart bot"
```

### Update UI & Kode Baru (Quick Redeploy)
- Karena folder `frontend/` di-mount langsung via volume Docker compose, pembaruan UI **cukup disinkronkan**:
```powershell
scp -r frontend studo@100.114.150.48:/home/studo/apps/goldscalper/
```
- Jika ada pembaruan backend (`core/`, `api/`, `agents/`, `runtime.py`):
```powershell
scp -r core api agents spk execution data runtime.py studo@100.114.150.48:/home/studo/apps/goldscalper/
ssh -t studo@100.114.150.48 "cd /home/studo/apps/goldscalper && sudo docker compose restart bot"
```

---

## 7. Rollback & Emergency Stop Plan

Jika terjadi anomali trading atau error fatal pada engine:

1. **Trigger Panic Close via Dashboard atau API:**
   * Buka Web Cockpit `https://scalper.7pivot.site` ➔ Menu `Control` ➔ Klik `EMERGENCY PANIC CLOSE`.
   * Atau via API curl langsung:
     ```powershell
     curl -X POST https://scalper.7pivot.site/api/control/panic -H "Authorization: Bearer <API_TOKEN>"
     ```
2. **Inspeksi Visual GUI MetaTrader 5 via Web VNC:**
   * Buka browser ke `http://100.114.150.48:9096` (KasmVNC interface MT5 di container `gs-mt5`).
   * Tab Trade ➔ Tutup manual posisi jika diperlukan.
3. **Emergency Stop Container Bot:**
   ```powershell
   ssh studo@100.114.150.48 "cd /home/studo/apps/goldscalper && sudo docker compose stop bot"
   ```
4. **Restart Ulang Bersih:**
   ```powershell
   ssh studo@100.114.150.48 "cd /home/studo/apps/goldscalper && sudo docker compose down"
   ssh studo@100.114.150.48 "cd /home/studo/apps/goldscalper && sudo docker compose up -d"
   ```
