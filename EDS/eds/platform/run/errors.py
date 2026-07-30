"""Run failures.

Almost everything that can be wrong with a run is an *issue* rather than an
exception, and that is the module's central shape. A run binds three objects
that were each valid on their own; what can go wrong is that they disagree, and
disagreements are plural. A plan for the wrong domain, a target that does not
exist and a stop condition that can never be reached are three separate facts,
and reporting only the first would send somebody round the loop three times.

Exceptions are reserved for a value that could not be constructed at all - a
tick count of zero, a run mode that contradicts its own targets. Those are
:class:`ValueError`, raised where the field is set, in keeping with the rest of
the platform.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RunError", "RunIssue", "RunValidationError"]


class RunError(Exception):
    """Base class for every run failure."""


@dataclass(frozen=True, slots=True)
class RunIssue:
    """One reason a run's parts do not agree.

    Attributes:
        subject: What the issue is about - a stage name, a domain name, a
            dataset. Empty when the issue is about the run as a whole.
        rule: Machine-readable rule identifier, such as ``"domain_mismatch"``.
        detail: Human-readable explanation naming what disagrees with what.
    """

    subject: str
    rule: str
    detail: str

    def __str__(self) -> str:
        """Render the issue for an error message."""
        return f"[{self.subject or '<run>'}] {self.rule}: {self.detail}"


class RunValidationError(RunError):
    """Raised when a run's parts cannot describe a coherent execution.

    Attributes:
        issues: Every issue found, in a deterministic order.
    """

    def __init__(self, issues: tuple[RunIssue, ...]) -> None:
        """Build the error from the issues that caused it.

        Args:
            issues: Every issue found. Must not be empty - an error with
                nothing to report is a bug in the validator, not a run
                failure.

        Raises:
            ValueError: If ``issues`` is empty.
        """
        if not issues:
            raise ValueError("RunValidationError requires at least one issue")
        self.issues = issues
        rendered = "; ".join(str(issue) for issue in issues)
        super().__init__(f"{len(issues)} run issue(s): {rendered}")
