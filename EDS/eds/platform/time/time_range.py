"""The period a simulation covers.

A :class:`TimeRange` is the *declared* period - where a simulation starts and,
optionally, where it stops. It is not where the simulation currently is; that
is the clock's business, and keeping the two apart is what lets the same range
describe every run of a project while each run sits at a different date.

The range is inclusive at both ends. "Simulate 2024" reads as
``TimeRange(date(2024, 1, 1), date(2024, 12, 31))``, and a reader should not
have to remember whether the last day is in or out. An open-ended range - no
end at all - is a first-class case rather than a sentinel date, because a
simulation that runs until somebody stops it is ordinary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from eds.platform.time.dates import format_simulation_date, parse_simulation_date
from eds.platform.time.errors import InvalidTimeRangeError

__all__ = ["TimeRange"]


@dataclass(frozen=True, slots=True)
class TimeRange:
    """An inclusive period of simulated time.

    Attributes:
        start: The first day of the period.
        end: The last day, or ``None`` for a period with no declared end.
    """

    start: date
    end: date | None = None

    def __post_init__(self) -> None:
        """Reject a period that could not be simulated.

        Raises:
            InvalidTimeRangeError: If the end precedes the start. A range whose
                end is before its start describes no days at all, and the two
                arguments were almost certainly supplied the wrong way round.
        """
        if self.end is not None and self.end < self.start:
            raise InvalidTimeRangeError(
                f"time range ends on {self.end.isoformat()}, before it starts on "
                f"{self.start.isoformat()}"
            )

    def __str__(self) -> str:
        """Render the period for a message."""
        end = self.end.isoformat() if self.end is not None else "open"
        return f"{self.start.isoformat()} to {end}"

    @property
    def is_open_ended(self) -> bool:
        """Report whether the period has no declared end."""
        return self.end is None

    @property
    def length_in_days(self) -> int | None:
        """Return how many days the period covers, both ends included.

        Returns:
            The day count, or ``None`` when the period is open-ended.
        """
        if self.end is None:
            return None
        return (self.end - self.start).days + 1

    def contains(self, day: date) -> bool:
        """Report whether a day falls inside the period.

        Args:
            day: The day to test.

        Returns:
            Whether the day is on or after the start and, if there is an end,
            on or before it.
        """
        if day < self.start:
            return False
        return self.end is None or day <= self.end

    def to_document(self) -> dict[str, Any]:
        """Render the period as a storable document.

        Returns:
            A plain mapping of primitives, with dates in ISO 8601.
        """
        return {
            "start": format_simulation_date(self.start),
            "end": format_simulation_date(self.end) if self.end is not None else None,
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> TimeRange:
        """Rebuild a period from a stored document.

        Args:
            document: The stored document.

        Returns:
            The period.

        Raises:
            InvalidDateError: If either date is absent or not ISO 8601.
            InvalidTimeRangeError: If the end precedes the start.
        """
        raw_end = document.get("end")
        end = None if raw_end is None else parse_simulation_date(raw_end, "time range end")
        return cls(start=parse_simulation_date(document.get("start"), "time range start"), end=end)
