"""Time model failures.

Each exception names one thing that can be wrong about simulated time, so a
caller can tell "your tick is nonsense" from "your range is nonsense" from "you
asked me to go backwards". Conflating them produces the unhelpful "invalid
time" that tells nobody anything.

Every one of them is a :class:`ValueError`. Each is raised because an argument
or a field could not be accepted, which is what ``ValueError`` means, and
inheriting from it keeps the platform's dataclass validation convention intact:
a frozen record rejects a bad field with a ``ValueError`` and a caller that only
wants to catch bad input does not need to know this module exists.
"""

from __future__ import annotations

__all__ = [
    "CalendarError",
    "InvalidAdvancementError",
    "InvalidDateError",
    "InvalidTickError",
    "InvalidTimeRangeError",
    "SimulationEndedError",
    "TimeError",
    "TimeOverflowError",
]


class TimeError(ValueError):
    """Base class for every simulated-time failure."""


class InvalidDateError(TimeError):
    """Raised when text cannot be read as a simulation date.

    Deliberately stricter than :meth:`datetime.date.fromisoformat`, which
    accepts several spellings of the same day. A simulation that reads dates
    from configuration should fail on ``"20240101"`` rather than quietly accept
    a second format nobody agreed to.
    """


class InvalidTickError(TimeError):
    """Raised when a tick could not advance time.

    A tick of zero or negative size would let a simulation loop without ever
    moving, which presents as a hang rather than as an error.
    """


class InvalidTimeRangeError(TimeError):
    """Raised when a range could not describe a simulated period.

    Covers an end before its start, and a clock positioned outside its own
    range.
    """


class CalendarError(TimeError):
    """Raised when a calendar could not answer a question about business days.

    Covers a weekday outside Monday-to-Sunday, a calendar on which no day is
    ever a business day, and a search for a business day that found none within
    the supported horizon.
    """


class InvalidAdvancementError(TimeError):
    """Raised when time was asked to move backwards.

    Simulated time is monotonic. Rewinding is not an advancement with a
    negative sign: it is a different operation, and one no component has asked
    for. Constructing an earlier clock is always available and is explicit.
    """


class TimeOverflowError(TimeError):
    """Raised when advancement would leave the range dates can represent.

    :data:`datetime.date` stops at 9999-12-31. A simulation that reaches it has
    a bug worth reporting rather than an arithmetic error worth propagating.
    """


class SimulationEndedError(TimeError):
    """Raised when advancement would pass a range's declared end.

    Refused rather than clamped. Silently stopping at the end would let a
    caller's loop spin forever on a clock that never changes, and silently
    running past it would produce data outside the period that was asked for.
    """
