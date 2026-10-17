"""SPK (Sistem Pengambilan Keputusan) consensus engine."""

from spk.decision import ACTION_BUY, ACTION_HOLD, ACTION_SELL, SPKDecision
from spk.veto import VetoParams, VetoResult
from spk.veto import evaluate as evaluate_vetoes
from spk.voting import SPKThresholds, VotingResult, action_for_score, aggregate

__all__ = [
    "ACTION_BUY",
    "ACTION_SELL",
    "ACTION_HOLD",
    "SPKDecision",
    "SPKThresholds",
    "VotingResult",
    "aggregate",
    "action_for_score",
    "VetoParams",
    "VetoResult",
    "evaluate_vetoes",
]
