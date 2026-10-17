#!/bin/bash
PASS='123qwe$$'

echo "=== CHECKING /etc/services.d OR /etc/s6-overlay ==="
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 ls -la /etc/services.d || true
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 ls -la /etc/s6-overlay/s6-rc.d || true
