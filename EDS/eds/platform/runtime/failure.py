"""What went wrong, and what was worth mentioning.

**A failure is a fact, not an exception.** It holds no traceback, no exception
object and no frames. That is not squeamishness: a contract has to survive
being written to a document and read back on another machine, and an exception
survives neither. A traceback also keeps every local variable in every frame
alive, which for this platform means a failed stage could pin an entire frame
of generated data in memory.

So ``cause`` is a string. Whatever produced the failure decides how much of the
original to render into it - usually ``repr(exc)`` - and the contract records
that rendering as a fact.

**No retry, no recovery, no severity ladder.** A failure says what happened.
Whether to retry it is a scheduler's policy, and a policy expressed as a field
here would be a policy the contract quietly enforced on everyone.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from eds.platform.runtime.documents import require_str
from eds.platform.runtime.errors import RuntimeContractError

__all__ = ["ExecutionWarning", "Failure", "FailureType"]


class FailureType(StrEnum):
    """What kind of thing went wrong.

    The taxonomy follows the four phases a stage actually passes through in
    this platform - configure, generate, validate, write - plus the two cases
    that are not about a stage's own work. It is deliberately derived from
    this architecture rather than from a generic severity model, because a
    generic taxonomy would tell a reader nothing they could act on.

    Attributes:
        CONFIGURATION: The run could not be set up - bad configuration, an
            unplannable domain, a project that does not validate. Nothing ran.
        GENERATION: A generator raised while producing data.
        VALIDATION: Data was produced and failed the validation framework.
            Distinct from ``GENERATION`` because the data exists and can be
            inspected.
        PERSISTENCE: Data was produced and validated and could not be written.
        DEPENDENCY: The stage did not run because something it needed failed.
            Not the stage's own fault, and a consumer counting real failures
            should be able to tell the difference.
        INTERNAL: A defect in the platform itself. Always worth reporting as a
            bug rather than as a configuration problem.
    """

    CONFIGURATION = "configuration"
    GENERATION = "generation"
    VALIDATION = "validation"
    PERSISTENCE = "persistence"
    DEPENDENCY = "dependency"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class Failure:
    """One reason something did not finish.

    Attributes:
        failure_type: What kind of thing went wrong.
        message: What happened, in a sentence somebody can act on.
        stage: The stage identifier this is about, or ``None`` when the
            failure is about the run as a whole - a configuration problem
            fails before any stage exists.
        cause: The underlying error rendered as text, usually ``repr(exc)``.
            Text rather than an exception, so the failure can be stored.
    """

    failure_type: FailureType
    message: str
    stage: str | None = None
    cause: str | None = None

    def __post_init__(self) -> None:
        """Reject a failure that explains nothing.

        Raises:
            RuntimeContractError: If the message is empty, or the stage is
                present but blank. A failure whose whole content is its type
                is a failure nobody can act on.
        """
        if not self.message.strip():
            raise RuntimeContractError("a failure must carry a message")
        if self.stage is not None and not self.stage.strip():
            raise RuntimeContractError(
                "a failure's stage must be a stage identifier or None, not blank"
            )

    def __str__(self) -> str:
        """Render the failure for an error message or a log line."""
        where = self.stage or "<run>"
        caused = f" (caused by {self.cause})" if self.cause else ""
        return f"[{where}] {self.failure_type.value}: {self.message}{caused}"

    def to_document(self) -> dict[str, Any]:
        """Render the failure as a storable document.

        Returns:
            A plain mapping of primitives.
        """
        return {
            "failure_type": self.failure_type.value,
            "message": self.message,
            "stage": self.stage,
            "cause": self.cause,
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> Failure:
        """Rebuild a failure from a stored document.

        Args:
            document: The stored document.

        Returns:
            The failure.

        Raises:
            RuntimeContractError: If a field is absent or malformed.
        """
        raw_type = document.get("failure_type")
        known = [member.value for member in FailureType]
        if not isinstance(raw_type, str) or raw_type not in known:
            raise RuntimeContractError(f"failure type {raw_type!r} is not one of {known}")

        stage = document.get("stage")
        if stage is not None and not isinstance(stage, str):
            raise RuntimeContractError(f"failure stage must be a string or null, found {stage!r}")

        cause = document.get("cause")
        if cause is not None and not isinstance(cause, str):
            raise RuntimeContractError(f"failure cause must be a string or null, found {cause!r}")

        return cls(
            failure_type=FailureType(raw_type),
            message=require_str(document, "message"),
            stage=stage,
            cause=cause,
        )


@dataclass(frozen=True, slots=True)
class ExecutionWarning:
    """Something worth reporting that did not stop the work.

    **Not a Python warning.** It is never raised, never passed to
    :mod:`warnings`, and has nothing to do with :class:`Warning`. It is a fact
    recorded in a result, and it is named for what a reader of that result
    calls it.

    The shape - subject, rule, detail - is the platform's, matching
    ``ValidationIssue``, ``PlanningIssue``, ``ProjectIssue`` and ``RunIssue``.
    A machine-readable ``rule`` is what lets a consumer count or filter
    warnings without parsing English.

    Attributes:
        subject: What the warning is about - a stage identifier, a dataset
            name. Empty when it is about the run as a whole.
        rule: Machine-readable identifier, such as ``"empty_dataset"``.
        detail: Human-readable explanation.
    """

    subject: str
    rule: str
    detail: str

    def __post_init__(self) -> None:
        """Reject a warning that cannot be acted on or counted.

        Raises:
            RuntimeContractError: If the rule or the detail is empty. The
                subject may be, and means the run itself.
        """
        if not self.rule.strip():
            raise RuntimeContractError("a warning must carry a machine-readable rule")
        if not self.detail.strip():
            raise RuntimeContractError("a warning must carry a detail")

    def __str__(self) -> str:
        """Render the warning for a log line."""
        return f"[{self.subject or '<run>'}] {self.rule}: {self.detail}"

    def to_document(self) -> dict[str, Any]:
        """Render the warning as a storable document.

        Returns:
            A plain mapping of primitives.
        """
        return {"subject": self.subject, "rule": self.rule, "detail": self.detail}

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> ExecutionWarning:
        """Rebuild a warning from a stored document.

        Args:
            document: The stored document.

        Returns:
            The warning.

        Raises:
            RuntimeContractError: If a field is absent or malformed.
        """
        return cls(
            subject=require_str(document, "subject"),
            rule=require_str(document, "rule"),
            detail=require_str(document, "detail"),
        )
