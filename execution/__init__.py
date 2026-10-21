"""Execution layer: pre-trade gating, order submission, and position management."""

from __future__ import annotations

from execution.order_manager import ExecutionResult, OrderManager
from execution.position_manager import PositionManager, PositionState
from execution.risk_gate import RiskGateResult, apply, evaluate
from execution.structural_guard import StructuralEvaluation, StructuralGuard, StructuralLevel

__all__ = [
    "OrderManager",
    "ExecutionResult",
    "PositionManager",
    "PositionState",
    "RiskGateResult",
    "apply",
    "evaluate",
    "StructuralGuard",
    "StructuralLevel",
    "StructuralEvaluation",
]

