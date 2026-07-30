"""Shared result types for the validation package."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

__all__ = ["ValidationError", "ValidationIssue", "format_issues"]


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A single validation failure.

    Attributes:
        dataset: Dataset the failure was found in.
        rule: Short identifier of the violated rule.
        detail: Human-readable description, including offending values where
            they are short enough to be useful.
    """

    dataset: str
    rule: str
    detail: str

    def __str__(self) -> str:
        """Render the issue as one diagnostic line."""
        return f"[{self.dataset}] {self.rule}: {self.detail}"


class ValidationError(Exception):
    """Raised when generated data fails validation.

    Attributes:
        issues: Every issue found, in discovery order.
    """

    def __init__(self, issues: Sequence[ValidationIssue]) -> None:
        """Build the error from the issues that caused it.

        Args:
            issues: The validation failures.
        """
        self.issues = tuple(issues)
        super().__init__(f"{len(self.issues)} validation issue(s):\n{format_issues(self.issues)}")


def format_issues(issues: Iterable[ValidationIssue]) -> str:
    """Render issues as a newline-separated, indented block.

    Args:
        issues: Issues to render.

    Returns:
        One indented line per issue, or ``"  (none)"`` when empty.
    """
    lines = [f"  {issue}" for issue in issues]
    return "\n".join(lines) if lines else "  (none)"
