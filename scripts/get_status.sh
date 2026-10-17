#!/bin/bash
TOKEN=$(grep API_TOKEN /home/studo/apps/goldscalper/.env | cut -d '=' -f2)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:9090/api/status | python3 -c '
import sys, json
data = json.load(sys.stdin)
print("=== BOT RUNTIME STATUS ===")
print("Paused:", data.get("paused"))
print("Orders Placed:", data.get("orders_placed"))
print("Balance:", data.get("balance"))
print("Equity:", data.get("equity"))
ld = data.get("last_decision") or {}
print("Last Decision Action:", ld.get("action"))
print("Last Decision Size:", ld.get("size"))
print("Last Decision Hard Veto:", ld.get("hard_veto"))
print("Positions count:", len(data.get("positions") or []))
print("Positions:", data.get("positions"))
'
