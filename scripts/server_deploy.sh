#!/bin/bash
set -e
cd /home/studo/apps/goldscalper
echo "123qwe\$\$" | sudo -S docker compose restart bot
echo "123qwe\$\$" | sudo -S docker ps --filter "name=gs-"
