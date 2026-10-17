#!/bin/bash
PASS='123qwe$$'
echo "$PASS" | sudo -S -p "" docker exec gs-bot python -c "
import json
from datetime import datetime

# Let's inspect what is in runtime.telemetry()
# We can import runtime or inspect the types
from api.server import app
import json

# Check json serialization of mock/real telemetry
from agents.state import SharedState
from spk.consensus import ConsensusDecision

d = ConsensusDecision(action='BUY', strength='NORMAL', score=1.5, confidence=0.8)
print('Decision division_scores:', type(d.division_scores), d.division_scores)
"
