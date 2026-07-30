"""The status of a run or a stage, and how one may move to another.

**One enum, not two.** A run and a stage share five of six statuses, and a
consumer formatting a log line or colouring a dashboard wants one vocabulary
rather than two that must be converted between. The single case that differs -
a run cannot be *skipped* - is enforced as a rule on
:class:`~eds.platform.runtime.results.RunResult` rather than paid for with a
second enum, a second transition table and a second serialisation.

**Results may only hold a terminal status.** ``PENDING`` and ``RUNNING``
describe a stage in flight; a *result* is a record of something that finished,
so a result carrying ``RUNNING`` would be a typed value that cannot be true.
Both result types refuse one at construction. The non-terminal statuses still
exist here because a scheduler needs to name where it is, and because a
transition model that omitted its own start states would not be a model.

The transitions are a **declared table**, not a state machine object. Nothing
here advances a status, checks a guard or fires a callback - it answers whether
a move is legal and stops. That is the same shape as Retail's
``PAYMENT_TRANSITIONS`` and ``ORDER_TRANSITIONS``, which are declared tables the
generators consult (ADR-012), and it is the shape that keeps this module free of
behaviour.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from eds.platform.runtime.errors import InvalidStatusTransitionError

__all__ = [
    "STATUS_TRANSITIONS",
    "TERMINAL_STATUSES",
    "ExecutionStatus",
    "is_valid_transition",
    "require_valid_transition",
]


class ExecutionStatus(StrEnum):
    """Where a run or a stage has got to.

    Attributes:
        PENDING: Declared, not started. Not a valid status for a result.
        RUNNING: Started, not finished. Not a valid status for a result.
        COMPLETED: Finished, and did what was asked.
        FAILED: Finished, and did not. Always carries a failure.
        SKIPPED: Deliberately not run - a resume passing over work already
            recorded as complete. A stage status only; a run is never skipped.
        CANCELLED: Stopped from outside before it could finish.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """Report whether nothing further can happen to this status."""
        return self in TERMINAL_STATUSES

    @property
    def is_successful(self) -> bool:
        """Report whether this status describes work that did what was asked.

        ``SKIPPED`` counts: a resume that passes over completed work has not
        gone wrong, and a caller asking "did this run cleanly?" should not have
        to enumerate the ways in which it might not have.
        """
        return self in (ExecutionStatus.COMPLETED, ExecutionStatus.SKIPPED)


#: The statuses nothing follows. A result may only carry one of these.
TERMINAL_STATUSES: Final[frozenset[ExecutionStatus]] = frozenset(
    {
        ExecutionStatus.COMPLETED,
        ExecutionStatus.FAILED,
        ExecutionStatus.SKIPPED,
        ExecutionStatus.CANCELLED,
    }
)

#: Which statuses may follow which. Declared, never executed.
#:
#: ``PENDING`` may go straight to ``SKIPPED`` because a resume decides not to
#: run a stage without ever starting it, and straight to ``CANCELLED`` because
#: a run may be stopped before it reaches a stage at all.
STATUS_TRANSITIONS: Final[Mapping[ExecutionStatus, frozenset[ExecutionStatus]]] = {
    ExecutionStatus.PENDING: frozenset(
        {ExecutionStatus.RUNNING, ExecutionStatus.SKIPPED, ExecutionStatus.CANCELLED}
    ),
    ExecutionStatus.RUNNING: frozenset(
        {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED}
    ),
    ExecutionStatus.COMPLETED: frozenset(),
    ExecutionStatus.FAILED: frozenset(),
    ExecutionStatus.SKIPPED: frozenset(),
    ExecutionStatus.CANCELLED: frozenset(),
}


def is_valid_transition(current: ExecutionStatus, following: ExecutionStatus) -> bool:
    """Report whether one status may follow another.

    Args:
        current: Where the run or stage is now.
        following: Where it would move to.

    Returns:
        Whether the move is declared in :data:`STATUS_TRANSITIONS`.
    """
    return following in STATUS_TRANSITIONS[current]


def require_valid_transition(current: ExecutionStatus, following: ExecutionStatus) -> None:
    """Check that one status may follow another.

    Offered so that a scheduler tracking a stage's lifecycle has one place to
    ask, rather than each caller reimplementing the table. It checks and
    raises; it does not perform the move, because there is nothing here to
    move.

    Args:
        current: Where the run or stage is now.
        following: Where it would move to.

    Raises:
        InvalidStatusTransitionError: If the move is not declared. The message
            names what would have been legal, including the case where nothing
            would have been.
    """
    if is_valid_transition(current, following):
        return
    allowed = sorted(status.value for status in STATUS_TRANSITIONS[current])
    if not allowed:
        raise InvalidStatusTransitionError(
            f"{current.value!r} is terminal, so nothing may follow it; "
            f"asked for {following.value!r}"
        )
    raise InvalidStatusTransitionError(
        f"{current.value!r} cannot be followed by {following.value!r}; allowed: {allowed}"
    )
