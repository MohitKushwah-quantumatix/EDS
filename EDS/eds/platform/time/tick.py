"""The tick: one logical advancement of simulated time.

A tick is a *size* and a *unit* - three days, one week, two months. It is pure
data plus the arithmetic for applying itself. It runs nothing, schedules
nothing, and holds no position in time; where the simulation currently is
belongs to the clock.

**There is no separate tick policy.** The obvious design has a ``TickPolicy``
strategy deciding which days a tick may land on, which in practice means one
question: does this tick skip non-business days? That question already has an
owner - the calendar - so a policy object would be a third collaborator whose
whole content is a flag. Instead ``BUSINESS_DAY`` is a unit like any other, and
the calendar supplies its meaning. Ticking three business days is
``Tick(3, TickUnit.BUSINESS_DAY)``, and what counts as a business day is the
calendar's business, exactly as it should be.

**Month arithmetic clamps and does not round-trip.** Advancing one month from
31 January lands on 28 February, and advancing back does not return to the
31st. That is the only defensible answer - there is no 31 February - but it
means month advancement is not reversible, which is why a clock derives its
elapsed tick count from its dates rather than trusting a stored counter.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import MAXYEAR, MINYEAR, date, timedelta
from enum import StrEnum
from typing import Any, Final

from eds.platform.time.calendar import (
    Calendar,
    ContinuousCalendar,
    add_business_days,
    business_days_between,
)
from eds.platform.time.errors import InvalidTickError, TimeOverflowError

__all__ = ["DAILY", "MONTHLY", "WEEKLY", "YEARLY", "Tick", "TickUnit"]

_MONTHS_IN_YEAR: Final[int] = 12


class TickUnit(StrEnum):
    """The unit a tick is measured in.

    ``BUSINESS_DAY`` is the one unit whose length is not fixed: it is defined
    by a calendar, so advancing by it consults one.
    """

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    BUSINESS_DAY = "business_day"


@dataclass(frozen=True, slots=True)
class Tick:
    """One logical advancement of simulated time.

    Attributes:
        size: How many units one tick covers. Must be at least 1.
        unit: What the size is counted in.
    """

    size: int = 1
    unit: TickUnit = TickUnit.DAY

    def __post_init__(self) -> None:
        """Reject a tick that could not move time forward.

        Raises:
            InvalidTickError: If the size is not a positive integer. A tick of
                zero would let a simulation loop without advancing, which
                presents as a hang rather than as an error, and a negative one
                would rewind.
        """
        if isinstance(self.size, bool) or not isinstance(self.size, int):
            raise InvalidTickError(f"tick size must be an integer, found {self.size!r}")
        if self.size < 1:
            raise InvalidTickError(f"tick size must be at least 1, found {self.size}")

    def __str__(self) -> str:
        """Render the tick for a message, such as ``"3 business days"``."""
        unit = self.unit.value.replace("_", " ")
        return f"{self.size} {unit}" if self.size == 1 else f"{self.size} {unit}s"

    @property
    def needs_calendar(self) -> bool:
        """Report whether applying this tick depends on a calendar."""
        return self.unit is TickUnit.BUSINESS_DAY

    def advance(self, start: date, count: int = 1, calendar: Calendar | None = None) -> date:
        """Return the date reached by applying this tick a number of times.

        Args:
            start: The date to advance from.
            count: How many ticks to apply. May be zero, which returns
                ``start``; may be negative, which is how a caller computes a
                date before another one. The clock refuses to move backwards,
                but that is the clock's rule, not the tick's.
            calendar: The calendar giving ``BUSINESS_DAY`` its meaning.
                Defaults to :class:`~eds.platform.time.calendar.ContinuousCalendar`,
                on which every day is a business day.

        Returns:
            The resulting date.

        Raises:
            TimeOverflowError: If the result would leave the range dates can
                represent.
            CalendarError: If a business day cannot be found within the
                calendar's search horizon.
        """
        if count == 0:
            return start
        units = self.size * count
        match self.unit:
            case TickUnit.DAY:
                return _add_days(start, units)
            case TickUnit.WEEK:
                return _add_days(start, units * 7)
            case TickUnit.MONTH:
                return _add_months(start, units)
            case TickUnit.YEAR:
                return _add_months(start, units * _MONTHS_IN_YEAR)
            case TickUnit.BUSINESS_DAY:
                return add_business_days(calendar or ContinuousCalendar(), start, units)

    def elapsed(self, start: date, current: date, calendar: Calendar | None = None) -> int:
        """Count the whole ticks between two dates.

        Derived rather than stored, so a clock restored from a persisted date
        reports the same count as one that reached that date by ticking. A
        date part-way through a tick counts the completed ticks only.

        Args:
            start: The date the simulation began at.
            current: The date it has reached.
            calendar: The calendar giving ``BUSINESS_DAY`` its meaning.

        Returns:
            The number of complete ticks, negative if ``current`` precedes
            ``start``.
        """
        if current == start:
            return 0
        # Python's // floors, which is what a tick count needs: a date before
        # the start yields a negative count rather than one rounded towards
        # zero, so the count stays monotonic across the start date.
        match self.unit:
            case TickUnit.DAY:
                return (current - start).days // self.size
            case TickUnit.WEEK:
                return (current - start).days // (self.size * 7)
            case TickUnit.BUSINESS_DAY:
                counted = business_days_between(calendar or ContinuousCalendar(), start, current)
                return counted // self.size
            case TickUnit.MONTH | TickUnit.YEAR:
                return self._elapsed_by_probe(start, current)

    def _elapsed_by_probe(self, start: date, current: date) -> int:
        """Count whole month or year ticks by testing candidate counts.

        Month arithmetic clamps, so subtracting month numbers is not reliable:
        one month after 31 January is 28 February, whose day-of-month is lower
        than the start's. The month difference is used as an estimate and then
        corrected against the arithmetic that actually performed the
        advancement, which makes the answer exact by construction.

        Args:
            start: The date the simulation began at.
            current: The date it has reached.

        Returns:
            The number of complete ticks.
        """
        months = self.size * (1 if self.unit is TickUnit.MONTH else _MONTHS_IN_YEAR)
        estimate = (_month_index(current) - _month_index(start)) // months
        while self.advance(start, estimate + 1) <= current:
            estimate += 1
        while self.advance(start, estimate) > current:
            estimate -= 1
        return estimate

    def to_document(self) -> dict[str, Any]:
        """Render the tick as a storable document.

        Returns:
            A plain mapping of primitives.
        """
        return {"size": self.size, "unit": self.unit.value}

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> Tick:
        """Rebuild a tick from a stored document.

        Args:
            document: The stored document.

        Returns:
            The tick.

        Raises:
            InvalidTickError: If the size or unit is absent or malformed.
        """
        size = document.get("size")
        if isinstance(size, bool) or not isinstance(size, int):
            raise InvalidTickError(f"tick size must be an integer, found {size!r}")
        raw_unit = document.get("unit")
        known = [member.value for member in TickUnit]
        if not isinstance(raw_unit, str):
            raise InvalidTickError(f"tick unit {raw_unit!r} is not one of {known}")
        try:
            unit = TickUnit(raw_unit)
        except ValueError as exc:
            raise InvalidTickError(f"tick unit {raw_unit!r} is not one of {known}") from exc
        return cls(size=size, unit=unit)


#: One day. The default, and what a daily simulation runs on.
DAILY: Final[Tick] = Tick(1, TickUnit.DAY)

#: One week.
WEEKLY: Final[Tick] = Tick(1, TickUnit.WEEK)

#: One month, clamped to the last day of shorter months.
MONTHLY: Final[Tick] = Tick(1, TickUnit.MONTH)

#: One year, clamping 29 February to the 28th in non-leap years.
YEARLY: Final[Tick] = Tick(1, TickUnit.YEAR)


def _add_days(start: date, days: int) -> date:
    """Add a number of days, reporting overflow as a time error.

    Args:
        start: The date to advance from.
        days: How many days to add. May be negative.

    Returns:
        The resulting date.

    Raises:
        TimeOverflowError: If the result is not representable.
    """
    try:
        return start + timedelta(days=days)
    except OverflowError as exc:
        raise TimeOverflowError(
            f"advancing {days} day(s) from {start.isoformat()} leaves the range "
            f"dates can represent ({date.min.isoformat()} to {date.max.isoformat()})"
        ) from exc


def _add_months(start: date, months: int) -> date:
    """Add a number of months, clamping to the target month's length.

    Args:
        start: The date to advance from.
        months: How many months to add. May be negative.

    Returns:
        The resulting date, with the day clamped to the last of the month when
        the original day does not exist there.

    Raises:
        TimeOverflowError: If the resulting year is not representable.
    """
    index = _month_index(start) + months
    year, month_offset = divmod(index, _MONTHS_IN_YEAR)
    month = month_offset + 1
    if not MINYEAR <= year <= MAXYEAR:
        raise TimeOverflowError(
            f"advancing {months} month(s) from {start.isoformat()} leaves the range "
            f"dates can represent (years {MINYEAR} to {MAXYEAR})"
        )
    return date(year, month, min(start.day, monthrange(year, month)[1]))


def _month_index(value: date) -> int:
    """Return a date's month as a count of months since year zero.

    Args:
        value: The date.

    Returns:
        The month index, so that consecutive months differ by one.
    """
    return value.year * _MONTHS_IN_YEAR + (value.month - 1)
