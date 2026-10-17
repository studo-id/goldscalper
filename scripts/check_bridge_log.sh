#!/bin/bash
PASS='123qwe$$'
echo "=== /tmp/bridge.log ==="
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 tail -n 60 /tmp/bridge.log || true
echo ""
echo "=== NETSTAT / SS INSIDE GS-MT5 ==="
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 ss -tlpn || true
