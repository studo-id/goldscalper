#!/bin/bash
set -e
PASS='123qwe$$'

echo "=== 1. Stopping any existing uvicorn in gs-mt5 ==="
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 pkill -f "uvicorn" || true
sleep 1

echo "=== 2. Starting FastAPI MT5 Bridge inside gs-mt5 on port 9095 ==="
echo "$PASS" | sudo -S -p "" docker exec -d -u abc -w "/config/.wine/drive_c" gs-mt5 env DISPLAY=:1 WINEPREFIX=/config/.wine wine "C:\\Program Files\\Python39\\python.exe" -m uvicorn bridge.app:app --host 0.0.0.0 --port 9095

echo "Waiting 5 seconds for bridge to initialize..."
sleep 5

echo "=== 3. Testing bridge endpoint directly from gs-bot ==="
echo -n "Health check: "
echo "$PASS" | sudo -S -p "" docker exec gs-bot curl -s "http://mt5:9095/health"
echo ""

echo -n "Tick check (XAUUSDm): "
echo "$PASS" | sudo -S -p "" docker exec gs-bot curl -s "http://mt5:9095/tick?symbol=XAUUSDm"
echo ""

echo "=== 4. Re-creating gs-bot with MT5_MOCK=false & MT5_BRIDGE_URL=http://mt5:9095 ==="
cd /home/studo/apps/goldscalper
echo "$PASS" | sudo -S -p "" docker compose up -d bot

echo "Waiting for gs-bot..."
sleep 5

echo "=== 5. Recent gs-bot logs ==="
echo "$PASS" | sudo -S -p "" docker logs --tail 25 gs-bot
echo "=== FINISHED ==="
