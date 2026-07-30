"""Planning failures.

Planning fails loudly. A graph that cannot be ordered has no valid plan, and
returning a partial plan alongside a list of complaints invites somebody to
execute it. So the planner raises, and the exception carries every issue found
rather than only the first, because a malformed pipeline usually has more than
one thing wrong with it.

These are distinct from :class:`~eds.core.validation.issues.ValidationIssue`,
which is about generated *data*. A plan is not data; it has stages rather than
datasets, and reusing the data type here would produce error messages that name
a "dataset" that is actually a stage.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PlanValidationError", "PlanningError", "PlanningIssue"]


@dataclass(frozen=True, slots=True)
class PlanningIssue:
    """One reason a set of stages cannot be planned.

    Attributes:
        stage: The offending stage name, or an empty string when the issue is
            about the graph as a whole rather than one stage.
        rule: Machine-readable rule identifier, such as ``"unknown_dependency"``.
        detail: Human-readable explanation naming what is wrong.
    """

    stage: str
    rule: str
    detail: str

    def __str__(self) -> str:
        """Render the issue for an error message."""
        subject = self.stage or "<plan>"
        return f"[{subject}] {self.rule}: {self.detail}"


class PlanningError(ValueError):
    """Base class for every planning failure."""


class PlanValidationError(PlanningError):
    """Raised when a set of stages cannot form a valid execution plan.

    Attributes:
        issues: Every issue found, in a deterministic order.
    """

    def __init__(self, issues: tuple[PlanningIssue, ...]) -> None:
        """Build the error from the issues that caused it.

        Args:
            issues: Every issue found. Must not be empty - an error with no
                issue is a bug in the validator, not a planning failure.

        Raises:
            ValueError: If ``issues`` is empty.
        """
        if not issues:
            raise ValueError("PlanValidationError requires at least one issue")
        self.issues = issues
        count = len(issues)
        rendered = "; ".join(str(issue) for issue in issues)
        super().__init__(f"{count} planning issue(s): {rendered}")
