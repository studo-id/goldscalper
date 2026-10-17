#!/bin/bash
PASS='123qwe$$'

echo "=== Positions from Bridge (Direct from MT5 Terminal) ==="
echo "$PASS" | sudo -S -p "" docker exec gs-bot curl -s http://mt5:9095/positions
echo ""

echo "=== MT5 Health & Account ==="
echo "$PASS" | sudo -S -p "" docker exec gs-bot curl -s http://mt5:9095/health
echo ""

TOKEN=$(grep API_TOKEN /home/studo/apps/goldscalper/.env | cut -d '=' -f2)
echo "=== GoldScalper API Positions ==="
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:9090/api/positions
echo ""
