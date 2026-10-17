#!/bin/bash
PASS='123qwe$$'

echo "=== Installing eval_type_backport in Wine Python 3.9 ==="
echo "$PASS" | sudo -S -p "" docker exec -u abc -w "/config/.wine/drive_c" gs-mt5 env DISPLAY=:1 WINEPREFIX=/config/.wine wine "C:\\Program Files\\Python39\\python.exe" -m pip install eval_type_backport

echo "=== Testing import again ==="
echo "$PASS" | sudo -S -p "" docker exec -u abc -w "/config/.wine/drive_c" gs-mt5 env DISPLAY=:1 WINEPREFIX=/config/.wine wine "C:\\Program Files\\Python39\\python.exe" -c "
import sys
sys.path.insert(0, 'C:\\\\')
import eval_type_backport
import bridge.app
print('SUCCESS: bridge.app imported cleanly!')
"
