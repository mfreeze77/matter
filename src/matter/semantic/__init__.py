"""Offline, provider-neutral typed semantic execution (MAT-026)."""

from .contracts import (
    Batch, BatchResult, Capabilities, Executor, FixtureExecutor, PrecisionProfile,
    Question, RawExecution, execute_batch, normalize_response,
)

__all__ = [
    "Batch", "BatchResult", "Capabilities", "Executor", "FixtureExecutor",
    "PrecisionProfile", "Question", "RawExecution", "execute_batch", "normalize_response",
]
