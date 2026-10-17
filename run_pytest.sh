#!/bin/bash
PASS='123qwe$$'
echo "$PASS" | sudo -S -p "" docker exec gs-bot pytest -q --ignore=tests/test_backtest.py
