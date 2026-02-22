"""Mitigation module for executing and rolling back actions."""

from .action_stack import ActionStack, ActionRecord, RollbackInfo
from .oracle import (
    OracleBase,
    ValidationResult,
    AlertsClearedOracle,
    ClusterHealthOracle,
    CompositeOracle,
)
from .severity import SeverityMetric, SeverityCalculator

__all__ = [
    "ActionStack",
    "ActionRecord",
    "RollbackInfo",
    "OracleBase",
    "ValidationResult",
    "AlertsClearedOracle",
    "ClusterHealthOracle",
    "CompositeOracle",
    "SeverityMetric",
    "SeverityCalculator",
]
