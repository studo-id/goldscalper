#!/bin/bash
PASS='123qwe$$'
echo "=== DOCKER PS FOR GOLD SCALPER CONTAINERS ==="
echo "$PASS" | sudo -S -p "" docker ps --filter "name=gs-"
echo ""
echo "=== GS-MT5 PROCESSES ==="
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 ps aux || true
echo ""
echo "=== TEST MT5 BRIDGE HEALTH FROM INSIDE GS-BOT ==="
echo "$PASS" | sudo -S -p "" docker exec gs-bot curl -v --max-time 3 http://mt5:9095/health || true
echo ""
echo "=== TEST MT5 BRIDGE HEALTH FROM INSIDE GS-MT5 ==="
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 curl -v --max-time 3 http://127.0.0.1:9095/health || true
