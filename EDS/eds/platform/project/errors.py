"""Project failures.

Each exception names one thing that can go wrong with a project on disk, so a
caller can distinguish "there is no project here" from "there is one but I
cannot read it" from "there is one and it is newer than I am". Those three
need different responses and conflating them produces the unhelpful "could not
load project" that tells nobody anything.

Structural problems that do not prevent loading - an unregistered domain, a
missing data directory - are reported as :class:`ProjectIssue` rather than
raised, because a project you cannot fully use is still a project you may want
to inspect.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "CorruptDocumentError",
    "ProjectError",
    "ProjectExistsError",
    "ProjectIssue",
    "ProjectNotFoundError",
    "ProjectValidationError",
    "StateStoreError",
    "UnsupportedVersionError",
]


class ProjectError(Exception):
    """Base class for every project failure."""


class ProjectNotFoundError(ProjectError):
    """Raised when no project exists at a location."""


class ProjectExistsError(ProjectError):
    """Raised when creating a project where one already exists.

    Creating over an existing project would discard its identity and its
    history, so it is refused rather than done silently.
    """


class UnsupportedVersionError(ProjectError):
    """Raised when a document's version is one this platform cannot read.

    A document written by a newer platform cannot be understood; one written
    by an older platform would need migration, which is not implemented. Both
    are reported here, with a message that says which case it is.
    """


class StateStoreError(ProjectError):
    """Raised when a store cannot read or write a document."""


class CorruptDocumentError(StateStoreError):
    """Raised when a stored document exists but cannot be understood.

    Distinct from :class:`StateStoreError` because the remedy differs: an I/O
    failure is worth retrying and a corrupt document is not.
    """


@dataclass(frozen=True, slots=True)
class ProjectIssue:
    """One structural problem with an otherwise loadable project.

    Attributes:
        subject: What the issue is about - a directory name, a domain name.
        rule: Machine-readable rule identifier, such as ``"unknown_domain"``.
        detail: Human-readable explanation.
    """

    subject: str
    rule: str
    detail: str

    def __str__(self) -> str:
        """Render the issue for an error message."""
        return f"[{self.subject or '<project>'}] {self.rule}: {self.detail}"


class ProjectValidationError(ProjectError):
    """Raised when a project's structure is not usable.

    Attributes:
        issues: Every issue found, in a deterministic order.
    """

    def __init__(self, issues: tuple[ProjectIssue, ...]) -> None:
        """Build the error from the issues that caused it.

        Args:
            issues: Every issue found. Must not be empty.

        Raises:
            ValueError: If ``issues`` is empty.
        """
        if not issues:
            raise ValueError("ProjectValidationError requires at least one issue")
        self.issues = issues
        rendered = "; ".join(str(issue) for issue in issues)
        super().__init__(f"{len(issues)} project issue(s): {rendered}")
