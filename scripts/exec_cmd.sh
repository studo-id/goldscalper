#!/bin/bash
set -e
echo "123qwe\$\$" | sudo -S docker exec gs-mt5 apt-get update
echo "123qwe\$\$" | sudo -S docker exec gs-mt5 apt-get install -y xdotool
echo "123qwe\$\$" | sudo -S docker exec -u abc gs-mt5 env DISPLAY=:1 xdotool key Escape
sleep 1
echo "=== Check windows after Escape ==="
echo "123qwe\$\$" | sudo -S docker exec -u abc gs-mt5 env DISPLAY=:1 xwininfo -root -tree | grep -iE "terminal" || true
