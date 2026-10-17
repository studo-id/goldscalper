#!/bin/bash
PASS='123qwe$$'
echo "=== DOCKER CONTAINERS STATUS ==="
echo "$PASS" | sudo -S -p "" docker ps -a
echo ""
echo "=== CHECKING GS-MT5 LOGS (last 30 lines) ==="
echo "$PASS" | sudo -S -p "" docker logs --tail 30 gs-mt5 || true
echo ""
echo "=== CHECKING GS-BOT LOGS (last 15 lines) ==="
echo "$PASS" | sudo -S -p "" docker logs --tail 15 gs-bot || true
