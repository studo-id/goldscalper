# GoldScalper MT5 Bridge — Windows Host Setup

The bridge runs on the Windows PC that hosts the MetaTrader 5 terminal (Exness). The Linux bot calls this HTTP bridge over Tailscale/LAN to send orders, query ticks/positions and fetch candles.

## 1. Prerequisites
- Windows 10/11 with MetaTrader 5 terminal installed and connected to Exness (demo account)
- Python 3.11+ installed
- Tailscale (or reachable LAN IP) from the Home-Server

## 2. Files
Copy the `bridge/` folder and `bridge/requirements.txt` to the Windows machine. Suggested location: `C:\GoldScalper\bridge\`.

## 3. Install dependencies
```powershell
cd C:\GoldScalper
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r bridge\requirements.txt
```

## 4. Configure .env
Create `.env` in `C:\GoldScalper\` (same root as bridge):
```env
BRIDGE_HOST=0.0.0.0
BRIDGE_PORT=9095
BRIDGE_TOKEN=bridge_token_rahasia
MT5_LOGIN=0
MT5_PASSWORD=your_mt5_password
MT5_SERVER=Exness-Real10
MT5_PATH=
MT5_DEVIATION=20
MT5_FILLING=IOC
```

Set `MT5_LOGIN` to your Exness demo account login. Keep `BRIDGE_TOKEN` identical to `MT5_BRIDGE_TOKEN` used by the Linux bot.

## 5. Start the bridge
```powershell
cd C:\GoldScalper
.\.venv\Scripts\Activate.ps1
python -m bridge.run
```

You should see: `Uvicorn running on http://0.0.0.0:9095`.

## 6. Test from Home-Server (Tailscale)
```bash
curl -H "Authorization: Bearer bridge_token_rahasia" http://100.114.201.115:9095/health
# => {"status": "ok", ...}
```

## 7. Security notes
- Bind to LAN/Tailscale IP or `0.0.0.0` only on a trusted network.
- Always use a strong `BRIDGE_TOKEN`.
- Do not expose 9095 to the public internet.
