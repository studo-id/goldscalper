#!/bin/bash
PASS='123qwe$$'

echo "=== CHECKING /config/.wine/drive_c/bridge ==="
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 ls -la /config/.wine/drive_c/bridge

echo "=== FIXING COPY TO /config/.wine/drive_c/ ==="
echo "$PASS" | sudo -S -p "" docker cp /home/studo/apps/goldscalper/bridge/backend.py gs-mt5:/config/.wine/drive_c/bridge/backend.py
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 chown -R abc:abc /config/.wine/drive_c/bridge

echo "=== TESTING DIRECT IMPORT NOW ==="
echo "$PASS" | sudo -S -p "" docker exec -u abc -w "/config/.wine/drive_c" gs-mt5 env DISPLAY=:1 WINEPREFIX=/config/.wine wine "C:\\Program Files\\Python39\\python.exe" -c "
import sys
sys.path.insert(0, 'C:\\\\')
import bridge.app
print('SUCCESS: bridge.app imported without error!')
"
