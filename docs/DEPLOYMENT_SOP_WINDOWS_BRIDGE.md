# SOP: Windows MT5 Bridge (ARCHIVED / DEPRECATED)

> [!WARNING]
> **STATUS: DEPRECATED & ARCHIVED (2026-10-14)**  
> Arsitektur Windows Bridge dipensiunkan agar workstation Windows PC dialokasikan **khusus untuk aplikasi `AcengGold`**.  
> Seluruh infrastruktur **GoldScalper** (Core Bot, TimescaleDB, Redis, dan MT5 Linux Runner) kini berjalan mandiri 24/7 di **Home-Server (`100.114.150.48`)**.  
> Dokumen ini dipertahankan hanya sebagai referensi historis bagi skenario dual-machine.

---

## 3a. Persiapan MT5 Bridge di Windows Host (Arsip Historis)

The bridge previously ran on the Windows machine running MetaTrader 5 (Exness demo). In the new architecture, MT5 runs containerized directly on Home-Server.

1. **Transfer files** — copy `bridge/` folder to `C:\GoldScalper\bridge\` on the Windows machine.
2. **Install deps**:
   ```powershell
   cd C:\GoldScalper
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r bridge\requirements.txt
   ```
3. **Configure `.env` on Windows** (create `C:\GoldScalper\.env`):
   ```env
   BRIDGE_HOST=0.0.0.0
   BRIDGE_PORT=9095
   BRIDGE_TOKEN=bridge_token_rahasia
   MT5_LOGIN=<your_exness_demo_login>
   MT5_PASSWORD=<your_mt5_password>
   MT5_SERVER=Exness-Real10
   MT5_DEVIATION=20
   MT5_FILLING=IOC
   ```
4. **Start bridge**:
   ```powershell
   cd C:\GoldScalper
   .\.venv\Scripts\Activate.ps1
   python -m bridge.run
   ```
5. **Verify reachability from Home-Server**:
   ```bash
   curl -H "Authorization: Bearer bridge_token_rahasia" http://100.114.201.115:9095/health
   ```

> Note: Linux bot uses `MT5_BRIDGE_URL=http://100.114.201.115:9095` and `MT5_BRIDGE_TOKEN=bridge_token_rahasia` (see .env on Home-Server).
