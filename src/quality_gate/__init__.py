"""Deterministic, advisory readiness checks for AI-generated changes."""

from .engine import GateInputError, evaluate

__all__ = ["GateInputError", "evaluate"]
