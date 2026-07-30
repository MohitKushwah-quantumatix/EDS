"""When a run should stop.

**A closed set, deliberately.** A stop condition is not an extension point: a
scheduler has to *interpret* every one that exists, so an open protocol would
let a caller construct a condition no scheduler knows how to honour. Declaring
the set here means adding a criterion is a considered platform change, and it
means a scheduler can match on them exhaustively and be told by its type
checker when a new one appears.

That is the opposite of the choice made for :class:`~eds.platform.time.calendar.Calendar`,
and for the opposite reason. A calendar is *asked* a question and answers it
itself, so anybody may write one. A stop condition is *read* by somebody else,
so only the platform may declare one.

**Nothing here stops anything.** Each condition is a description of a criterion
a scheduler will evaluate. There is no loop, no counter, no state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "STOP_CONDITION_KINDS",
    "AfterStage",
    "AfterTicks",
    "EndOfPeriod",
    "StopCondition",
    "stop_condition_from_document",
]


@dataclass(frozen=True, slots=True)
class EndOfPeriod:
    """Stop when the clock reaches the end of its declared period.

    The default, and the only condition that needs no configuration. It
    requires the clock to *have* an end: paired with an open-ended period it
    can never be satisfied, which a run reports as an issue rather than
    discovering after an unbounded number of ticks.
    """

    @property
    def kind(self) -> str:
        """Return the condition's discriminator."""
        return "end_of_period"

    def __str__(self) -> str:
        """Render the condition for a message."""
        return "at the end of the simulated period"

    def to_document(self) -> dict[str, Any]:
        """Render the condition as a storable document.

        Returns:
            A plain mapping of primitives.
        """
        return {"kind": self.kind}


@dataclass(frozen=True, slots=True)
class AfterTicks:
    """Stop after a fixed number of ticks.

    Attributes:
        count: How many ticks to run. At least one - a run that stops after
            zero ticks is a run that was not wanted.
    """

    count: int

    def __post_init__(self) -> None:
        """Reject a tick count that could not describe a run.

        Raises:
            ValueError: If the count is not a positive integer.
        """
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise ValueError(f"stop-after-ticks count must be an integer, found {self.count!r}")
        if self.count < 1:
            raise ValueError(f"stop-after-ticks count must be at least 1, found {self.count}")

    @property
    def kind(self) -> str:
        """Return the condition's discriminator."""
        return "after_ticks"

    def __str__(self) -> str:
        """Render the condition for a message."""
        return f"after {self.count} tick(s)"

    def to_document(self) -> dict[str, Any]:
        """Render the condition as a storable document.

        Returns:
            A plain mapping of primitives.
        """
        return {"kind": self.kind, "count": self.count}


@dataclass(frozen=True, slots=True)
class AfterStage:
    """Stop once a named stage has completed.

    Attributes:
        stage: The stage's own name, unqualified - the same spelling a plan
            uses. A run checks that the plan actually contains it, because a
            condition naming a stage that will never run is a condition that
            will never fire.
    """

    stage: str

    def __post_init__(self) -> None:
        """Reject a condition that names nothing.

        Raises:
            ValueError: If the stage name is empty or blank.
        """
        if not self.stage.strip():
            raise ValueError("stop-after-stage requires a stage name")

    @property
    def kind(self) -> str:
        """Return the condition's discriminator."""
        return "after_stage"

    def __str__(self) -> str:
        """Render the condition for a message."""
        return f"after the {self.stage!r} stage"

    def to_document(self) -> dict[str, Any]:
        """Render the condition as a storable document.

        Returns:
            A plain mapping of primitives.
        """
        return {"kind": self.kind, "stage": self.stage}


#: Every criterion a run may stop on. Closed: a scheduler matches on all of
#: them, so adding one is a platform change rather than a caller's choice.
type StopCondition = EndOfPeriod | AfterTicks | AfterStage

#: The discriminators, for error messages that say what would have worked.
STOP_CONDITION_KINDS: Final[tuple[str, ...]] = ("end_of_period", "after_ticks", "after_stage")


def stop_condition_from_document(document: dict[str, Any]) -> StopCondition:
    """Rebuild a stop condition from a stored document.

    Args:
        document: The stored document, discriminated by its ``kind``.

    Returns:
        The condition.

    Raises:
        ValueError: If the kind is absent or unknown, or if the condition's
            own fields are malformed.
    """
    kind = document.get("kind")
    match kind:
        case "end_of_period":
            return EndOfPeriod()
        case "after_ticks":
            count = document.get("count")
            if isinstance(count, bool) or not isinstance(count, int):
                raise ValueError(f"stop-after-ticks count must be an integer, found {count!r}")
            return AfterTicks(count)
        case "after_stage":
            stage = document.get("stage")
            if not isinstance(stage, str):
                raise ValueError(f"stop-after-stage stage must be a string, found {stage!r}")
            return AfterStage(stage)
        case _:
            raise ValueError(
                f"stop condition kind {kind!r} is not one of {list(STOP_CONDITION_KINDS)}"
            )
