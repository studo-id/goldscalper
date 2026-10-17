#!/bin/bash
echo "123qwe\$\$" | sudo -S docker exec gs-mt5 grep -rn "Failed to start the mt5linux" / 2>/dev/null
