#!/bin/bash
PASS='123qwe$$'

echo "=== Updating .env on server ==="
sed -i 's/^MAX_OPEN_POSITIONS=.*/MAX_OPEN_POSITIONS=10/' /home/studo/apps/goldscalper/.env
grep "MAX_OPEN_POSITIONS" /home/studo/apps/goldscalper/.env

echo "=== Copying updated config/settings.py ==="
cp /home/studo/apps/goldscalper/config/settings.py /home/studo/apps/goldscalper/config/settings.py.bak || true

echo "=== Restarting gs-bot container ==="
echo "$PASS" | sudo -S -p "" docker restart gs-bot
sleep 4

echo "=== Checking recent gs-bot logs ==="
echo "$PASS" | sudo -S -p "" docker logs --tail 25 gs-bot
