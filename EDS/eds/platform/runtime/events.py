"""What happened, in the order it happened.

Six events, and a **closed set**. The same reasoning as P005's stop conditions:
a consumer has to interpret every kind that exists, so an open hierarchy would
let a producer emit something no consumer knows how to read. Closed means a
``match`` over them is exhaustive and a type checker says so when a seventh
arrives.

**Ordering is a sequence number, not a timestamp.** No event carries wall-clock
time. Two runs of the same simulation with the same seed must produce the same
event stream, and a stream stamped with ``datetime.now()`` never would - it
could not be compared, stored as a fixture, or asserted on. So each event
carries a monotonic ``sequence`` and the simulated date it happened on, which
is what makes the stream a deterministic fact rather than a recording.

**There is no bus.** No emitter, no subscriber, no observer, no dispatch. These
are values. A scheduler produces them into a tuple; whatever wants them reads
that tuple. Anything more is transport, and transport is not a contract.

Results and events overlap on purpose, and they are not redundant. A result
answers "what is the state of things now"; the stream answers "how did it get
there". A stage that started and never finished has a ``StageStarted`` and no
result at all, which is precisely the case a result cannot express.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from eds.platform.runtime.documents import require_date, require_int, require_str
from eds.platform.runtime.errors import RuntimeContractError
from eds.platform.runtime.failure import Failure
from eds.platform.time.dates import format_simulation_date

__all__ = [
    "EXECUTION_EVENT_KINDS",
    "ExecutionEvent",
    "RunCompleted",
    "RunFailed",
    "RunStarted",
    "StageCompleted",
    "StageFailed",
    "StageStarted",
    "execution_event_from_document",
    "in_sequence",
]


def _check_common(sequence: int, run_id: str) -> None:
    """Reject an event that could not be placed in a stream.

    Args:
        sequence: The event's position.
        run_id: The run it belongs to.

    Raises:
        RuntimeContractError: If the sequence is negative or the run is
            unnamed. An event that cannot say which run it belongs to cannot
            be read alongside any other.
    """
    if sequence < 0:
        raise RuntimeContractError(f"an event's sequence cannot be negative, found {sequence}")
    if not run_id.strip():
        raise RuntimeContractError("an event must name the run it belongs to")


@dataclass(frozen=True, slots=True)
class RunStarted:
    """A run began.

    Attributes:
        sequence: Position in the stream. Zero for the first event.
        run_id: The run this belongs to.
        simulation_date: The simulated date the run began at.
        stage_count: How many stages the plan held, so a consumer can size a
            progress bar from the first event it sees.
    """

    sequence: int
    run_id: str
    simulation_date: date
    stage_count: int = 0

    def __post_init__(self) -> None:
        """Reject an event that could not be placed in a stream.

        Raises:
            RuntimeContractError: If the sequence is negative, the run is
                unnamed, or the stage count is negative.
        """
        _check_common(self.sequence, self.run_id)
        if self.stage_count < 0:
            raise RuntimeContractError(f"stage_count cannot be negative, found {self.stage_count}")

    @property
    def kind(self) -> str:
        """Return the event's discriminator."""
        return "run_started"

    def __str__(self) -> str:
        """Render the event for a log line."""
        return f"#{self.sequence} run {self.run_id} started with {self.stage_count} stage(s)"

    def to_document(self) -> dict[str, Any]:
        """Render the event as a storable document.

        Returns:
            A plain mapping of primitives.
        """
        return _common_document(self) | {"stage_count": self.stage_count}


@dataclass(frozen=True, slots=True)
class StageStarted:
    """A stage began.

    Attributes:
        sequence: Position in the stream.
        run_id: The run this belongs to.
        simulation_date: The simulated date the stage began at.
        stage_id: The stage's stable identifier.
    """

    sequence: int
    run_id: str
    simulation_date: date
    stage_id: str

    def __post_init__(self) -> None:
        """Reject an event that names no stage.

        Raises:
            RuntimeContractError: If the sequence is negative, or the run or
                stage is unnamed.
        """
        _check_common(self.sequence, self.run_id)
        _check_stage(self.stage_id)

    @property
    def kind(self) -> str:
        """Return the event's discriminator."""
        return "stage_started"

    def __str__(self) -> str:
        """Render the event for a log line."""
        return f"#{self.sequence} stage {self.stage_id} started"

    def to_document(self) -> dict[str, Any]:
        """Render the event as a storable document.

        Returns:
            A plain mapping of primitives.
        """
        return _common_document(self) | {"stage_id": self.stage_id}


@dataclass(frozen=True, slots=True)
class StageCompleted:
    """A stage finished successfully.

    Attributes:
        sequence: Position in the stream.
        run_id: The run this belongs to.
        simulation_date: The simulated date the stage ended at.
        stage_id: The stage's stable identifier.
        rows: How many rows it produced in total. A count rather than the
            per-dataset breakdown, which belongs on the stage's result - an
            event says that something happened, not everything about it.
    """

    sequence: int
    run_id: str
    simulation_date: date
    stage_id: str
    rows: int = 0

    def __post_init__(self) -> None:
        """Reject an event that could not describe a completion.

        Raises:
            RuntimeContractError: If the sequence is negative, the run or
                stage is unnamed, or the row count is negative.
        """
        _check_common(self.sequence, self.run_id)
        _check_stage(self.stage_id)
        if self.rows < 0:
            raise RuntimeContractError(f"a row count cannot be negative, found {self.rows}")

    @property
    def kind(self) -> str:
        """Return the event's discriminator."""
        return "stage_completed"

    def __str__(self) -> str:
        """Render the event for a log line."""
        return f"#{self.sequence} stage {self.stage_id} completed with {self.rows} row(s)"

    def to_document(self) -> dict[str, Any]:
        """Render the event as a storable document.

        Returns:
            A plain mapping of primitives.
        """
        return _common_document(self) | {"stage_id": self.stage_id, "rows": self.rows}


@dataclass(frozen=True, slots=True)
class StageFailed:
    """A stage did not finish.

    Attributes:
        sequence: Position in the stream.
        run_id: The run this belongs to.
        simulation_date: The simulated date it failed on.
        stage_id: The stage's stable identifier.
        failure: Why it failed. Required - an event that says a stage failed
            without saying why is worse than no event, because it looks like
            information.
    """

    sequence: int
    run_id: str
    simulation_date: date
    stage_id: str
    failure: Failure

    def __post_init__(self) -> None:
        """Reject an event that could not describe a failure.

        Raises:
            RuntimeContractError: If the sequence is negative, or the run or
                stage is unnamed.
        """
        _check_common(self.sequence, self.run_id)
        _check_stage(self.stage_id)

    @property
    def kind(self) -> str:
        """Return the event's discriminator."""
        return "stage_failed"

    def __str__(self) -> str:
        """Render the event for a log line."""
        return f"#{self.sequence} stage {self.stage_id} failed: {self.failure.message}"

    def to_document(self) -> dict[str, Any]:
        """Render the event as a storable document.

        Returns:
            A plain mapping of primitives.
        """
        return _common_document(self) | {
            "stage_id": self.stage_id,
            "failure": self.failure.to_document(),
        }


@dataclass(frozen=True, slots=True)
class RunCompleted:
    """A run finished successfully.

    Attributes:
        sequence: Position in the stream.
        run_id: The run this belongs to.
        simulation_date: The simulated date it reached.
        stage_count: How many stages finished successfully.
    """

    sequence: int
    run_id: str
    simulation_date: date
    stage_count: int = 0

    def __post_init__(self) -> None:
        """Reject an event that could not describe a completion.

        Raises:
            RuntimeContractError: If the sequence is negative, the run is
                unnamed, or the stage count is negative.
        """
        _check_common(self.sequence, self.run_id)
        if self.stage_count < 0:
            raise RuntimeContractError(f"stage_count cannot be negative, found {self.stage_count}")

    @property
    def kind(self) -> str:
        """Return the event's discriminator."""
        return "run_completed"

    def __str__(self) -> str:
        """Render the event for a log line."""
        return f"#{self.sequence} run {self.run_id} completed {self.stage_count} stage(s)"

    def to_document(self) -> dict[str, Any]:
        """Render the event as a storable document.

        Returns:
            A plain mapping of primitives.
        """
        return _common_document(self) | {"stage_count": self.stage_count}


@dataclass(frozen=True, slots=True)
class RunFailed:
    """A run did not finish.

    Attributes:
        sequence: Position in the stream.
        run_id: The run this belongs to.
        simulation_date: The simulated date it stopped on.
        failure: Why it failed. Required, for the same reason as
            :class:`StageFailed`.
    """

    sequence: int
    run_id: str
    simulation_date: date
    failure: Failure

    def __post_init__(self) -> None:
        """Reject an event that could not be placed in a stream.

        Raises:
            RuntimeContractError: If the sequence is negative or the run is
                unnamed.
        """
        _check_common(self.sequence, self.run_id)

    @property
    def kind(self) -> str:
        """Return the event's discriminator."""
        return "run_failed"

    def __str__(self) -> str:
        """Render the event for a log line."""
        return f"#{self.sequence} run {self.run_id} failed: {self.failure.message}"

    def to_document(self) -> dict[str, Any]:
        """Render the event as a storable document.

        Returns:
            A plain mapping of primitives.
        """
        return _common_document(self) | {"failure": self.failure.to_document()}


#: Everything that can happen during a run. Closed: a consumer matches on all
#: of them, so adding one is a platform change rather than a producer's choice.
type ExecutionEvent = (
    RunStarted | StageStarted | StageCompleted | StageFailed | RunCompleted | RunFailed
)

#: The discriminators, for error messages that say what would have worked.
EXECUTION_EVENT_KINDS: Final[tuple[str, ...]] = (
    "run_started",
    "stage_started",
    "stage_completed",
    "stage_failed",
    "run_completed",
    "run_failed",
)


def in_sequence(events: tuple[ExecutionEvent, ...]) -> tuple[ExecutionEvent, ...]:
    """Return the events ordered by their sequence numbers.

    A stream may be assembled out of order - concurrent stages at one
    dependency level finish when they finish - so ordering is derived from the
    numbers the producer assigned rather than from arrival. The sort is stable,
    so events sharing a sequence keep the order they were given in.

    Args:
        events: The events, in any order.

    Returns:
        The same events, ordered.
    """
    return tuple(sorted(events, key=lambda event: event.sequence))


def execution_event_from_document(document: dict[str, Any]) -> ExecutionEvent:
    """Rebuild an event from a stored document.

    Args:
        document: The stored document, discriminated by its ``kind``.

    Returns:
        The event.

    Raises:
        RuntimeContractError: If the kind is absent or unknown, or if the
            event's own fields are malformed.
    """
    kind = document.get("kind")
    sequence = require_int(document, "sequence")
    run_id = require_str(document, "run_id")
    when = require_date(document, "simulation_date")

    match kind:
        case "run_started":
            return RunStarted(sequence, run_id, when, require_int(document, "stage_count"))
        case "stage_started":
            return StageStarted(sequence, run_id, when, require_str(document, "stage_id"))
        case "stage_completed":
            return StageCompleted(
                sequence,
                run_id,
                when,
                require_str(document, "stage_id"),
                require_int(document, "rows"),
            )
        case "stage_failed":
            return StageFailed(
                sequence,
                run_id,
                when,
                require_str(document, "stage_id"),
                _failure_from(document),
            )
        case "run_completed":
            return RunCompleted(sequence, run_id, when, require_int(document, "stage_count"))
        case "run_failed":
            return RunFailed(sequence, run_id, when, _failure_from(document))
        case _:
            raise RuntimeContractError(
                f"event kind {kind!r} is not one of {list(EXECUTION_EVENT_KINDS)}"
            )


def _check_stage(stage_id: str) -> None:
    """Reject an event that names no stage.

    Args:
        stage_id: The stage identifier.

    Raises:
        RuntimeContractError: If it is empty or blank.
    """
    if not stage_id.strip():
        raise RuntimeContractError("a stage event must name its stage")


def _common_document(event: ExecutionEvent) -> dict[str, Any]:
    """Render the fields every event carries.

    Args:
        event: The event.

    Returns:
        The shared part of its document.
    """
    return {
        "kind": event.kind,
        "sequence": event.sequence,
        "run_id": event.run_id,
        "simulation_date": format_simulation_date(event.simulation_date),
    }


def _failure_from(document: dict[str, Any]) -> Failure:
    """Read the required failure out of an event document.

    Args:
        document: The stored document.

    Returns:
        The failure.

    Raises:
        RuntimeContractError: If it is absent or not an object.
    """
    raw = document.get("failure")
    if not isinstance(raw, dict):
        raise RuntimeContractError(f"a failure event must carry a failure, found {raw!r}")
    return Failure.from_document(raw)
