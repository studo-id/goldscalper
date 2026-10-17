#!/bin/bash
PASS='123qwe$$'
LINES=${1:-80}
echo "$PASS" | sudo -S -p "" docker logs --tail "$LINES" gs-bot
