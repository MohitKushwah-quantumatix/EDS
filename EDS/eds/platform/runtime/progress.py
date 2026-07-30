"""How far along a run is.

The one contract that describes something *in flight*. A result records what
finished; progress records a moment during. That is why it holds no status: a
snapshot saying "running" would be saying the only thing it could ever say.

**Percentages are optional, and that is the design.** An open-ended run has no
total tick count, so its tick percentage is not a small number or a zero - it
does not exist, and :data:`None` is the only honest answer. A consumer that
must render something can choose what to show; a consumer told ``0.0`` would
render a lie.

Four numbers, and no more. No throughput, no estimated completion, no rate: a
platform that has never executed anything has no basis for any of them, and a
speculative metric is a number somebody will believe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eds.platform.runtime.documents import require_int
from eds.platform.runtime.errors import RuntimeContractError

__all__ = ["Progress"]


@dataclass(frozen=True, slots=True)
class Progress:
    """How much of a run is done.

    Attributes:
        completed_stages: How many stages have reached a terminal status,
            including skipped ones - a skipped stage is done, not pending.
        total_stages: How many stages the plan holds.
        completed_ticks: How many ticks the clock has advanced.
        total_ticks: How many ticks the run expects to advance, or ``None``
            when the period is open-ended and there is no total to know.
    """

    completed_stages: int = 0
    total_stages: int = 0
    completed_ticks: int = 0
    total_ticks: int | None = None

    def __post_init__(self) -> None:
        """Reject progress that could not describe a run.

        Raises:
            RuntimeContractError: If a count is negative, or more is complete
                than exists. Progress past 100% is not optimism; it means the
                producer is counting two different things.
        """
        for name, value in (
            ("completed_stages", self.completed_stages),
            ("total_stages", self.total_stages),
            ("completed_ticks", self.completed_ticks),
        ):
            if value < 0:
                raise RuntimeContractError(f"{name} cannot be negative, found {value}")
        if self.completed_stages > self.total_stages:
            raise RuntimeContractError(
                f"{self.completed_stages} stage(s) complete out of {self.total_stages}"
            )
        if self.total_ticks is not None:
            if self.total_ticks < 0:
                raise RuntimeContractError(
                    f"total_ticks cannot be negative, found {self.total_ticks}"
                )
            if self.completed_ticks > self.total_ticks:
                raise RuntimeContractError(
                    f"{self.completed_ticks} tick(s) complete out of {self.total_ticks}"
                )

    def __str__(self) -> str:
        """Render the progress for a log line."""
        ticks = (
            f"{self.completed_ticks}"
            if self.total_ticks is None
            else (f"{self.completed_ticks}/{self.total_ticks}")
        )
        return f"{self.completed_stages}/{self.total_stages} stages, {ticks} ticks"

    @property
    def remaining_stages(self) -> int:
        """Return how many stages have not finished."""
        return self.total_stages - self.completed_stages

    @property
    def remaining_ticks(self) -> int | None:
        """Return how many ticks are left, or ``None`` for an open-ended run."""
        if self.total_ticks is None:
            return None
        return self.total_ticks - self.completed_ticks

    @property
    def stage_percentage(self) -> float | None:
        """Return the share of stages finished, 0 to 100.

        ``None`` when the plan holds no stages, because nought out of nought
        is not nought per cent.
        """
        if self.total_stages == 0:
            return None
        return 100.0 * self.completed_stages / self.total_stages

    @property
    def tick_percentage(self) -> float | None:
        """Return the share of ticks advanced, 0 to 100.

        ``None`` when the run is open-ended or expects no ticks - there is no
        denominator, and inventing one would be inventing a number.
        """
        if not self.total_ticks:
            return None
        return 100.0 * self.completed_ticks / self.total_ticks

    @property
    def is_complete(self) -> bool:
        """Report whether every stage has finished."""
        return self.total_stages > 0 and self.completed_stages == self.total_stages

    def to_document(self) -> dict[str, Any]:
        """Render the progress as a storable document.

        Returns:
            A plain mapping of primitives. The percentages are derived and are
            deliberately not stored - a stored derived value is a value that
            can disagree with what it was derived from.
        """
        return {
            "completed_stages": self.completed_stages,
            "total_stages": self.total_stages,
            "completed_ticks": self.completed_ticks,
            "total_ticks": self.total_ticks,
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> Progress:
        """Rebuild progress from a stored document.

        Args:
            document: The stored document.

        Returns:
            The progress.

        Raises:
            RuntimeContractError: If a field is absent, malformed, or
                impossible.
        """
        raw_total_ticks = document.get("total_ticks")
        if raw_total_ticks is not None and (
            isinstance(raw_total_ticks, bool) or not isinstance(raw_total_ticks, int)
        ):
            raise RuntimeContractError(
                f"field 'total_ticks' must be an integer or null, found {raw_total_ticks!r}"
            )
        return cls(
            completed_stages=require_int(document, "completed_stages"),
            total_stages=require_int(document, "total_stages"),
            completed_ticks=require_int(document, "completed_ticks"),
            total_ticks=raw_total_ticks,
        )
