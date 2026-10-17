#!/bin/bash
PASS='123qwe$$'
echo "$PASS" | sudo -S -p "" docker exec gs-mt5 ls -la /custom-services.d /etc/s6-overlay 2>&1 || true
