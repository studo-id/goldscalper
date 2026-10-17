#!/bin/bash
PASS='123qwe$$'
echo "=== Restarting gs-bot ==="
echo "$PASS" | sudo -S -p "" docker restart gs-bot
sleep 4
echo "=== gs-bot logs ==="
echo "$PASS" | sudo -S -p "" docker logs --tail 25 gs-bot
