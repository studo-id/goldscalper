#!/bin/bash
PASS='123qwe$$'

# 1. Update bridge python code
echo "=== Updating bridge code inside gs-mt5 ==="
echo "$PASS" | sudo -S -p "" docker cp /home/studo/apps/goldscalper/bridge/. gs-mt5:/config/.wine/drive_c/bridge/

# 2. Copy supervised runner script into gs-mt5
echo "=== Installing supervised runner script in gs-mt5 ==="
echo "$PASS" | sudo -S -p "" docker cp /home/studo/apps/goldscalper/scripts/run_bridge_supervised.sh gs-mt5:/config/run_bridge_supervised.sh
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 chmod +x /config/run_bridge_supervised.sh

# 3. Kill old un-supervised uvicorn processes
echo "=== Killing old bridge processes in gs-mt5 ==="
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 pkill -9 -f "run_bridge_supervised" || true
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 pkill -9 -f "uvicorn" || true
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 pkill -9 -f "bridge.app" || true
sleep 2

# 4. Start supervised bridge loop in gs-mt5
echo "=== Starting supervised MT5 bridge runner in gs-mt5 ==="
echo "$PASS" | sudo -S -p "" docker exec -d -u abc gs-mt5 /bin/bash /config/run_bridge_supervised.sh
sleep 5

# 5. Restart gs-bot container
echo "=== Restarting gs-bot container ==="
echo "$PASS" | sudo -S -p "" docker restart gs-bot
sleep 4

# 6. Setup host-level cron watchdog
echo "=== Configuring host cron watchdog ==="
chmod +x /home/studo/apps/goldscalper/scripts/bridge_watchdog.sh
(crontab -l 2>/dev/null | grep -v "bridge_watchdog.sh"; echo "* * * * * /bin/bash /home/studo/apps/goldscalper/scripts/bridge_watchdog.sh >/dev/null 2>&1") | crontab -

# 7. Verification
echo "=== Verifying /health from gs-bot to mt5:9095 ==="
echo "$PASS" | sudo -S -p "" docker exec gs-bot curl -s http://mt5:9095/health
echo ""

echo "=== Verifying /api/status telemetry on gs-bot ==="
TOKEN=$(grep API_TOKEN /home/studo/apps/goldscalper/.env | cut -d '=' -f2)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:9090/api/status | python3 -c '
import sys, json
data = json.load(sys.stdin)
print("mt5_trade_allowed:", data.get("mt5_trade_allowed"))
print("algo_trading:", data.get("algo_trading"))
print("orders_placed:", data.get("orders_placed"))
'
