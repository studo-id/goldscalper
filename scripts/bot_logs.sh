#!/bin/bash
PASS='123qwe$$'
echo "$PASS" | sudo -S docker logs --tail 25 gs-bot
