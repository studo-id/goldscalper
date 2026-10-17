#!/bin/bash
# Autonomous Host Watchdog for GoldScalper MT5 Bridge
# Can be run via cron every 1 minute.
# Auto-detects bridge unresponsiveness and revives the bridge in < 5 seconds.

PASS='123qwe$$'
LOGFILE="/home/studo/apps/goldscalper/logs/watchdog.log"
mkdir -p "/home/studo/apps/goldscalper/logs"

# Check health from gs-bot to mt5:9095 with strict 3-second timeout
HEALTH=$(echo "$PASS" | sudo -S -p "" docker exec gs-bot curl -s --max-time 3 http://mt5:9095/health 2>/dev/null || true)

if echo "$HEALTH" | grep -q '"status":"ok"'; then
    # All healthy, exit silently
    exit 0
fi

# If we reach here, bridge is unresponsive!
TIMESTAMP=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
echo "[$TIMESTAMP] [ALERT] MT5 Bridge healthcheck failed: '$HEALTH'. Initiating auto-recovery..." >> "$LOGFILE"

# 1. Kill any hung uvicorn / python processes in gs-mt5
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 pkill -9 -f "run_bridge_supervised" 2>/dev/null || true
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 pkill -9 -f "uvicorn" 2>/dev/null || true
sleep 1

# 2. Start supervised bridge loop in gs-mt5
echo "$PASS" | sudo -S -p "" docker exec -d -u abc gs-mt5 /bin/bash /config/run_bridge_supervised.sh
sleep 4

# 3. Restart gs-bot container to re-anchor websocket and connections
echo "$PASS" | sudo -S -p "" docker restart gs-bot >/dev/null 2>&1
sleep 3

# 4. Verify recovery
NEW_HEALTH=$(echo "$PASS" | sudo -S -p "" docker exec gs-bot curl -s --max-time 3 http://mt5:9095/health 2>/dev/null || true)
if echo "$NEW_HEALTH" | grep -q '"status":"ok"'; then
    echo "[$TIMESTAMP] [RECOVERED] MT5 Bridge successfully auto-recovered and healthy!" >> "$LOGFILE"
else
    echo "[$TIMESTAMP] [ERROR] Auto-recovery completed but healthcheck still failing: '$NEW_HEALTH'" >> "$LOGFILE"
fi
