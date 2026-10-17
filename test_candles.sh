#!/bin/bash
TOKEN=$(grep "^API_TOKEN=" /home/studo/apps/goldscalper/.env | cut -d= -f2)
echo "=== TESTING H4 ==="
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:9090/api/candles?tf=H4&limit=10" | cut -c 1-150
echo ""
echo "=== TESTING D1 ==="
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:9090/api/candles?tf=D1&limit=10" | cut -c 1-150
echo ""
