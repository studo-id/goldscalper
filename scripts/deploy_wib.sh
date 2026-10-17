#!/bin/bash
set -e
cd /home/studo/apps/goldscalper
PASS='123qwe$$'

echo "=== 1. Restarting gs-bot container ==="
echo "$PASS" | sudo -S docker compose restart bot
sleep 3

echo "=== 2. Running pytest inside gs-bot ==="
echo "$PASS" | sudo -S docker exec gs-bot pytest -q --ignore=tests/test_backtest.py

echo "=== 3. Checking Health Endpoint ==="
curl -s http://localhost:9090/health
echo ""

echo "=== 4. Checking Performance API for Today (WIB) ==="
curl -s "http://localhost:9090/api/performance?period=today" | jq -r '.period, .since, .until, .total_trades' || true
