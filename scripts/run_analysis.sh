#!/bin/bash
PASS='123qwe$$'
echo "$PASS" | sudo -S docker cp /home/studo/apps/goldscalper/scripts/analyze_today_trades.py gs-bot:/app/scripts/analyze_today_trades.py
echo "$PASS" | sudo -S docker exec gs-bot python /app/scripts/analyze_today_trades.py
