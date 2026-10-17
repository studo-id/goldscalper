#!/bin/bash
PASS='123qwe$$'

echo "=== Copying check_terminal.py to MT5 container ==="
echo "$PASS" | sudo -S -p "" docker cp /home/studo/apps/goldscalper/scripts/check_terminal.py gs-mt5:/config/.wine/drive_c/check_terminal.py

echo "=== Running check_terminal.py BEFORE ==="
echo "$PASS" | sudo -S -p "" docker exec -u abc -w "/config/.wine/drive_c" gs-mt5 env DISPLAY=:1 WINEPREFIX=/config/.wine wine "C:\\Program Files\\Python39\\python.exe" C:\\check_terminal.py

echo "=== Sending Ctrl+E to MT5 ==="
echo "$PASS" | sudo -S -p "" docker exec -u abc gs-mt5 env DISPLAY=:1 xdotool search --onlyvisible --class "terminal64.exe" windowactivate --sync key --clearmodifiers ctrl+e || true

sleep 2

echo "=== Running check_terminal.py AFTER ==="
echo "$PASS" | sudo -S -p "" docker exec -u abc -w "/config/.wine/drive_c" gs-mt5 env DISPLAY=:1 WINEPREFIX=/config/.wine wine "C:\\Program Files\\Python39\\python.exe" C:\\check_terminal.py
