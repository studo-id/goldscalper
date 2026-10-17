#!/bin/bash
set -e
echo "Testing bridge import from C:\\..."
echo "123qwe\$\$" | sudo -S -p "" docker exec -u abc -w "/config/.wine/drive_c/bridge" gs-mt5 env DISPLAY=:1 WINEPREFIX=/config/.wine wine "C:\\Program Files\\Python39\\python.exe" -c "
import sys
sys.path.insert(0, 'C:\\\\')
import bridge.app
print('SUCCESS: bridge.app imported from C:\\\\!')
"
