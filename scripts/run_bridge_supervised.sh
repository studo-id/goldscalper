#!/bin/bash
# Supervised launcher for MT5 FastAPI Bridge inside Wine container
# Ensures uvicorn is immediately auto-restarted if it ever crashes or exits.

export DISPLAY=:1
export WINEPREFIX=/config/.wine
cd /config/.wine/drive_c

echo "[watchdog] Starting MT5 Bridge supervisor loop..."

while true; do
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Starting MT5 Bridge uvicorn on port 9095..."
    wine "C:\\Program Files\\Python39\\python.exe" -m uvicorn bridge.app:app --host 0.0.0.0 --port 9095
    EXIT_CODE=$?
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] MT5 Bridge exited with code $EXIT_CODE. Restarting in 2 seconds..."
    sleep 2
done
