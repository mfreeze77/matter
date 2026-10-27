"""Offline, provider-neutral typed semantic execution (MAT-026)."""

from .contracts import (
    Batch, BatchResult, Capabilities, Executor, FixtureExecutor, PrecisionProfile,
    Question, RawExecution, execute_batch, normalize_response,
)
from .questions import (
    QuestionError, QuestionRegistry, QuestionSpecification, association_specification,
    comparison_specification, semantic_diff,
)
from .rendering import RenderedQuestion, render_question

__all__ = [
    "Batch", "BatchResult", "Capabilities", "Executor", "FixtureExecutor",
    "PrecisionProfile", "Question", "RawExecution", "execute_batch", "normalize_response",
    "QuestionError", "QuestionRegistry", "QuestionSpecification", "association_specification",
    "comparison_specification", "semantic_diff", "RenderedQuestion", "render_question",
]
