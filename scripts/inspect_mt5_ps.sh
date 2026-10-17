#!/bin/bash
PASS='123qwe$$'
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 ps aux
