#!/bin/bash
PASS='123qwe$$'

echo "=== CHECKING GS-MT5 PROCESSES ==="
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 ps aux | grep -i python

echo "=== CHECKING WINE PYTHON COMMAND DIRECTLY ==="
echo "$PASS" | sudo -S -p "" docker exec -u abc -w "/config/.wine/drive_c" gs-mt5 env DISPLAY=:1 WINEPREFIX=/config/.wine wine "C:\\Program Files\\Python39\\python.exe" -c "
import sys
sys.path.insert(0, 'C:\\\\')
import uvicorn
import bridge.app
print('Uvicorn and bridge.app loaded OK!')
"

echo "=== RUNNING BRIDGE MANUALLY WITH LOGGING ==="
echo "$PASS" | sudo -S -p "" docker exec -u abc -w "/config/.wine/drive_c" gs-mt5 env DISPLAY=:1 WINEPREFIX=/config/.wine wine "C:\\Program Files\\Python39\\python.exe" -m uvicorn bridge.app:app --host 0.0.0.0 --port 9095 &
PID=$!
sleep 4
echo "=== CHECKING PORT 9095 FROM INSIDE GS-MT5 ==="
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 curl -v "http://127.0.0.1:9095/health" || echo "Local curl failed"
kill $PID 2>/dev/null || true
