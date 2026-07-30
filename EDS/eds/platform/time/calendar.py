"""Business calendars: which days a simulated enterprise is open.

**A calendar answers exactly one question:** is this day a business day? Every
other operation - the next business day, the previous one, adding business
days, counting them - is derived from that predicate by the functions in this
module.

That split is deliberate. If the protocol declared six methods, every
replacement calendar would have to implement six, and any one of them could
disagree with the other five: a calendar whose ``next_business_day`` returned a
day its own ``is_business_day`` rejects is a bug that no type checker would
catch. With one method there is nothing to keep consistent.

**No country is assumed.** The weekend is a configurable set of weekdays,
because a Friday-Saturday weekend is as ordinary as a Saturday-Sunday one, and
holidays are supplied by the caller. This module ships no holiday list and
never will; a jurisdiction's calendar is data, and data belongs to whoever is
simulating that jurisdiction.

The default calendar is :class:`ContinuousCalendar`, on which every day is a
business day. A clock that has not been told about weekends should not invent
them.
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Final, Protocol, runtime_checkable

from eds.platform.time.dates import format_simulation_date, parse_simulation_date
from eds.platform.time.errors import CalendarError, TimeOverflowError

__all__ = [
    "MAX_CALENDAR_SEARCH_DAYS",
    "BusinessCalendar",
    "Calendar",
    "ContinuousCalendar",
    "add_business_days",
    "business_days_between",
    "next_business_day",
    "previous_business_day",
]

#: How far a search for a business day will look before giving up. Ten years
#: of consecutive closure is not a calendar anybody meant to configure, and
#: failing loudly beats searching to the year 9999.
MAX_CALENDAR_SEARCH_DAYS: Final[int] = 3_653

#: Monday is 0 and Sunday is 6, matching :meth:`datetime.date.weekday`.
_WEEKDAYS: Final[frozenset[int]] = frozenset(range(7))

_ONE_DAY: Final[timedelta] = timedelta(days=1)


@runtime_checkable
class Calendar(Protocol):
    """Decides which days a simulated enterprise does business on.

    Implementations must be pure and deterministic: the same day must always
    get the same answer, on every machine and in every run. A calendar that
    consulted the wall clock, a network service or a random draw would make a
    simulation irreproducible, which is the one property the platform will not
    trade (PADR-004, ADR-005).
    """

    @property
    def name(self) -> str:
        """Return the calendar's kind, such as ``"continuous"``."""
        ...

    def is_business_day(self, day: date) -> bool:
        """Report whether the enterprise is open on a day.

        Args:
            day: The day to test.

        Returns:
            Whether it is a business day.
        """
        ...


@dataclass(frozen=True, slots=True)
class ContinuousCalendar:
    """A calendar on which every day is a business day.

    The default, and the only honest one for a simulation that has not been
    told when its enterprise is closed. Satisfies :class:`Calendar`.
    """

    @property
    def name(self) -> str:
        """Return the calendar's kind."""
        return "continuous"

    def is_business_day(self, day: date) -> bool:
        """Report that the enterprise is open.

        Args:
            day: The day to test. Unused; every day qualifies.

        Returns:
            Always ``True``.
        """
        del day
        return True

    def to_document(self) -> dict[str, Any]:
        """Render the calendar as a storable document.

        Returns:
            A plain mapping of primitives.
        """
        return {"kind": self.name}


@dataclass(frozen=True, slots=True)
class BusinessCalendar:
    """A calendar with a configurable weekend and an optional holiday list.

    Satisfies :class:`Calendar`.

    Attributes:
        weekend_days: Weekday numbers that are not business days, where Monday
            is 0 and Sunday is 6, matching :meth:`datetime.date.weekday`.
            Defaults to Saturday and Sunday - a convention, stated in one
            place and overridable, rather than an assumption buried in logic.
        holidays: Individual days that are not business days regardless of
            weekday. Supplied by the caller; this module ships none.
        label: The calendar's name, so several regional calendars in one
            simulation can be told apart.
    """

    weekend_days: AbstractSet[int] = frozenset({5, 6})
    holidays: AbstractSet[date] = field(default_factory=frozenset)
    label: str = "business"

    def __post_init__(self) -> None:
        """Normalise the sets and reject a calendar that could not be used.

        Raises:
            CalendarError: If a weekday is outside 0-6, or if every weekday is
                a weekend - a calendar with no business day at all cannot
                answer any of the derived questions, and would present as a
                search that never terminates rather than as a configuration
                mistake.
        """
        weekend = frozenset(self.weekend_days)
        if invalid := sorted(weekend - _WEEKDAYS):
            raise CalendarError(f"weekend days must be 0 (Monday) to 6 (Sunday), found {invalid}")
        if weekend == _WEEKDAYS:
            raise CalendarError("a calendar whose every weekday is a weekend has no business day")
        object.__setattr__(self, "weekend_days", weekend)
        object.__setattr__(self, "holidays", frozenset(self.holidays))

    @property
    def name(self) -> str:
        """Return the calendar's kind."""
        return self.label

    def is_business_day(self, day: date) -> bool:
        """Report whether the enterprise is open on a day.

        Args:
            day: The day to test.

        Returns:
            Whether the day is neither a weekend day nor a holiday.
        """
        return day.weekday() not in self.weekend_days and day not in self.holidays

    def to_document(self) -> dict[str, Any]:
        """Render the calendar as a storable document.

        Returns:
            A plain mapping of primitives, with both sets sorted so the same
            calendar always produces the same document.
        """
        return {
            "kind": "business",
            "label": self.label,
            "weekend_days": sorted(self.weekend_days),
            "holidays": [format_simulation_date(day) for day in sorted(self.holidays)],
        }

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> BusinessCalendar:
        """Rebuild a calendar from a stored document.

        Args:
            document: The stored document.

        Returns:
            The calendar.

        Raises:
            CalendarError: If a field is absent or malformed.
            InvalidDateError: If a holiday is not an ISO 8601 date.
        """
        weekend = document.get("weekend_days", [])
        if not isinstance(weekend, list) or not all(
            isinstance(value, int) and not isinstance(value, bool) for value in weekend
        ):
            raise CalendarError(
                f"calendar weekend_days must be a list of integers, found {weekend!r}"
            )

        holidays = document.get("holidays", [])
        if not isinstance(holidays, list):
            raise CalendarError(f"calendar holidays must be a list of dates, found {holidays!r}")

        label = document.get("label", "business")
        if not isinstance(label, str):
            raise CalendarError(f"calendar label must be a string, found {label!r}")

        return cls(
            weekend_days=frozenset(weekend),
            holidays=frozenset(parse_simulation_date(day, "holiday") for day in holidays),
            label=label,
        )


def next_business_day(calendar: Calendar, day: date) -> date:
    """Return the first business day strictly after a day.

    Args:
        calendar: The calendar to consult.
        day: The day to start from.

    Returns:
        The next business day.

    Raises:
        CalendarError: If no business day is found within
            :data:`MAX_CALENDAR_SEARCH_DAYS`.
        TimeOverflowError: If the search would pass the last representable
            date.
    """
    return _step(calendar, day, forward=True)


def previous_business_day(calendar: Calendar, day: date) -> date:
    """Return the last business day strictly before a day.

    Args:
        calendar: The calendar to consult.
        day: The day to start from.

    Returns:
        The previous business day.

    Raises:
        CalendarError: If no business day is found within
            :data:`MAX_CALENDAR_SEARCH_DAYS`.
        TimeOverflowError: If the search would pass the first representable
            date.
    """
    return _step(calendar, day, forward=False)


def add_business_days(calendar: Calendar, day: date, count: int) -> date:
    """Move a number of business days from a day.

    Args:
        calendar: The calendar to consult.
        day: The day to start from.
        count: How many business days to move. Negative moves backwards; zero
            returns the day unchanged, whether or not it is a business day.

    Returns:
        The resulting day.

    Raises:
        CalendarError: If a business day cannot be found within
            :data:`MAX_CALENDAR_SEARCH_DAYS` of any step.
        TimeOverflowError: If the walk would leave the representable range.
    """
    forward = count > 0
    current = day
    for _ in range(abs(count)):
        current = _step(calendar, current, forward=forward)
    return current


def business_days_between(calendar: Calendar, start: date, end: date) -> int:
    """Count the business days from one day to another.

    Counts the half-open interval ``(start, end]``, which is what makes it the
    inverse of :func:`add_business_days`: adding *n* business days to ``start``
    lands on a day with exactly *n* business days between them.

    Args:
        calendar: The calendar to consult.
        start: The day to count from, itself excluded.
        end: The day to count to, itself included.

    Returns:
        The count, negative when ``end`` precedes ``start``.
    """
    if end == start:
        return 0
    if end < start:
        return -business_days_between(calendar, end, start)
    total = 0
    current = start + _ONE_DAY
    while current <= end:
        if calendar.is_business_day(current):
            total += 1
        current += _ONE_DAY
    return total


def _step(calendar: Calendar, day: date, forward: bool) -> date:
    """Return the nearest business day strictly on one side of a day.

    Args:
        calendar: The calendar to consult.
        day: The day to start from.
        forward: Whether to search forwards.

    Returns:
        The nearest business day in that direction.

    Raises:
        CalendarError: If none is found within :data:`MAX_CALENDAR_SEARCH_DAYS`.
        TimeOverflowError: If the search leaves the representable range.
    """
    stride = _ONE_DAY if forward else -_ONE_DAY
    current = day
    for _ in range(MAX_CALENDAR_SEARCH_DAYS):
        try:
            current = current + stride
        except OverflowError as exc:
            raise TimeOverflowError(
                f"searching for a business day from {day.isoformat()} left the "
                "range dates can represent"
            ) from exc
        if calendar.is_business_day(current):
            return current
    direction = "after" if forward else "before"
    raise CalendarError(
        f"calendar {calendar.name!r} has no business day within "
        f"{MAX_CALENDAR_SEARCH_DAYS} days {direction} {day.isoformat()}"
    )
