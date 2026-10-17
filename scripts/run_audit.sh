#!/bin/bash
PASS='123qwe$$'
echo "$PASS" | sudo -S -p "" docker cp /home/studo/apps/goldscalper/scripts/analyze_24h_juggler.py gs-bot:/app/scripts/analyze_24h_juggler.py
echo "$PASS" | sudo -S -p "" docker exec gs-bot python /app/scripts/analyze_24h_juggler.py
