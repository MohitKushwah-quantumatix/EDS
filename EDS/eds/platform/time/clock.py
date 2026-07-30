"""The simulation clock: where a simulation currently is in simulated time.

**The clock is immutable. Advancing produces a new clock.**

That is the central decision of this module, and it was not the obvious one.
A mutable clock reads more naturally in a loop - ``clock.advance()`` and carry
on - and it is what most simulation frameworks ship. It was rejected for four
reasons, in increasing order of weight:

1. It would be the only mutable thing in the platform. ``ExecutionPlan``,
   ``PlannedStage``, ``ProjectManifest``, ``SimulationState``, ``Workspace``
   and ``Project`` are all frozen records. A clock that mutated would be an
   exception a reader has to remember.
2. Advancement would stop being a function. ``clock.advance(5)`` twice would
   give two different answers, so a value that was read, logged or compared
   could not be trusted to still mean what it said.
3. A mutable clock is shared hidden state. Two components holding one would
   see each other's advancement, and PADR-004 requires a run to remain a pure
   function of ``(project, seed, upstream data)``. Passing time by value keeps
   that property mechanical rather than a matter of discipline.
4. It would disagree with the state model. P003's ``SimulationState`` is frozen
   and replaced. If state is replaced while the clock is mutated, the two drift
   apart in exactly the way that is hardest to notice; as values, they cannot.

The cost is real and worth stating: a caller must rebind the result, and a
dropped ``clock.advance()`` is a silent no-op. That is the same bargain
:class:`datetime.date` and :class:`pathlib.Path` already make, so it is at
least a familiar one.

**The calendar is a collaborator, not a component.** It is held by the clock
but owned by nobody: it is a strategy, injected at construction, replaceable
without touching this module, and asked exactly one question. Building weekends
into the clock would have made every enterprise a five-day one, and building a
calendar *hierarchy* into it would have made the clock the place regional
holiday rules go to accumulate. A clock that consults a calendar can be given a
different one; a clock that *is* a calendar cannot.

**The elapsed tick count is derived, never stored.** A stored counter would be
wrong the moment a clock was restored from a persisted date - P003 stores the
date, not the count - and month arithmetic clamps, so it could not be
recomputed by subtraction either. Deriving it from ``(start, tick, calendar,
current_date)`` means a restored clock and a ticked one always agree.

**A tick is a grid, not a step.** Advancement is measured from the period's
start rather than from wherever the clock happens to be, because month
arithmetic is not associative under clamping: five single-month steps from 31
January reach 29 June, while one five-month advancement reaches 30 June.
Relative stepping would also make the derived count disagree with the number of
advancements made. Anchoring costs one recomputation per advance and buys the
property that stepping, jumping and restoring all land on the same dates.

Nothing here executes anything. The clock moves a date. What should happen on
each tick is the scheduler's question, and the scheduler does not exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from eds.platform.time.calendar import Calendar, ContinuousCalendar
from eds.platform.time.errors import (
    InvalidAdvancementError,
    InvalidTimeRangeError,
    SimulationEndedError,
)
from eds.platform.time.tick import DAILY, Tick
from eds.platform.time.time_range import TimeRange

__all__ = ["SimulationClock", "create_clock"]


@dataclass(frozen=True, slots=True)
class SimulationClock:
    """Where a simulation has reached, and how it moves.

    Attributes:
        time_range: The period being simulated.
        current_date: The day the simulation has reached. Always inside
            ``time_range``.
        tick: How far one advancement moves.
        calendar: Which days the enterprise does business on. Consulted only
            by business-day ticks and by :attr:`is_business_day`, but held
            always, so that a clock fully describes how it moves.
    """

    time_range: TimeRange
    current_date: date
    tick: Tick = DAILY
    calendar: Calendar = field(default_factory=ContinuousCalendar)

    def __post_init__(self) -> None:
        """Reject a clock that could not describe a position in its period.

        Raises:
            InvalidTimeRangeError: If the current date is outside the range.
                A clock before its start has not begun, and one past its end
                has finished; neither is a position the simulation can be in.
        """
        if not self.time_range.contains(self.current_date):
            raise InvalidTimeRangeError(
                f"current date {self.current_date.isoformat()} is outside the "
                f"simulated period {self.time_range}"
            )

    def __str__(self) -> str:
        """Render the clock for a message."""
        return f"{self.current_date.isoformat()} (tick {self.tick}, of {self.time_range})"

    @property
    def start(self) -> date:
        """Return the first day of the simulated period."""
        return self.time_range.start

    @property
    def end(self) -> date | None:
        """Return the last day of the simulated period, if one was declared."""
        return self.time_range.end

    @property
    def is_open_ended(self) -> bool:
        """Report whether the simulated period has no declared end."""
        return self.time_range.is_open_ended

    @property
    def ticks_elapsed(self) -> int:
        """Return how many whole ticks separate the start from now.

        Derived from the dates rather than counted during advancement, so a
        clock restored from a persisted date reports the same number as one
        that ticked its way here. A date part-way through a tick counts only
        the completed ticks.
        """
        return self.tick.elapsed(self.time_range.start, self.current_date, self.calendar)

    @property
    def is_business_day(self) -> bool:
        """Report whether the enterprise is open on the current date."""
        return self.calendar.is_business_day(self.current_date)

    @property
    def is_finished(self) -> bool:
        """Report whether the clock has reached the end of its period.

        Always ``False`` for an open-ended period, which by construction has
        nothing to reach.
        """
        return self.time_range.end is not None and self.current_date >= self.time_range.end

    def remaining_days(self) -> int | None:
        """Return how many days are left, the current date excluded.

        Returns:
            The count, or ``None`` when the period is open-ended.
        """
        if self.time_range.end is None:
            return None
        return (self.time_range.end - self.current_date).days

    def advance(self, count: int = 1) -> SimulationClock:
        """Return a clock advanced by whole ticks.

        Measured from the period's start, not from the current date. That is
        not a detail: month advancement clamps, so stepping one month at a time
        from 31 January would reach 29 June while jumping five months at once
        reaches 30 June, and after five ``advance()`` calls the clock would
        report four elapsed ticks. Anchoring to the start makes the tick a grid
        the clock moves along, so stepping and jumping agree and the count
        cannot drift.

        Args:
            count: How many ticks to apply. Zero returns this clock unchanged,
                which keeps a caller's loop simple.

        Returns:
            A new clock at the resulting date. This clock is unchanged.

        Raises:
            InvalidAdvancementError: If ``count`` is negative. Simulated time
                is monotonic; constructing an earlier clock is a different
                operation and an explicit one.
            SimulationEndedError: If the result would pass the declared end.
            TimeOverflowError: If the result would not be representable.
            CalendarError: If a business-day tick finds no business day.
        """
        if count < 0:
            raise InvalidAdvancementError(
                f"cannot advance by {count} ticks: simulated time does not run backwards"
            )
        if count == 0:
            return self
        return self._moved_to(
            self.tick.advance(self.start, self.ticks_elapsed + count, self.calendar),
            f"advancing {count} tick(s) of {self.tick}",
        )

    def advance_to(self, target: date) -> SimulationClock:
        """Return a clock repositioned to a given date.

        A jump, not a sequence of ticks: the target need not fall on a tick
        boundary. Nothing drifts as a result, because
        :attr:`ticks_elapsed` is derived from the date rather than counted, so
        a clock moved here reports the same elapsed ticks as one that arrived
        by ticking.

        Args:
            target: The date to move to. Must be on or after the current date.

        Returns:
            A new clock at that date. This clock is unchanged.

        Raises:
            InvalidAdvancementError: If the target precedes the current date.
            SimulationEndedError: If the target is past the declared end.
        """
        if target < self.current_date:
            raise InvalidAdvancementError(
                f"cannot advance to {target.isoformat()}: the clock is already at "
                f"{self.current_date.isoformat()} and simulated time does not run backwards"
            )
        if target == self.current_date:
            return self
        return self._moved_to(target, f"advancing to {target.isoformat()}")

    def _moved_to(self, target: date, what: str) -> SimulationClock:
        """Return a clock at a date, refusing to pass the declared end.

        Args:
            target: The date to move to.
            what: What was attempted, for the error message.

        Returns:
            A new clock at that date.

        Raises:
            SimulationEndedError: If the target is past the end. Refused rather
                than clamped: stopping silently would let a caller's loop spin
                on a clock that never changes.
        """
        end = self.time_range.end
        if end is not None and target > end:
            raise SimulationEndedError(
                f"{what} from {self.current_date.isoformat()} reaches "
                f"{target.isoformat()}, past the simulated period's end of {end.isoformat()}"
            )
        return replace(self, current_date=target)


def create_clock(
    start: date,
    end: date | None = None,
    tick: Tick = DAILY,
    calendar: Calendar | None = None,
) -> SimulationClock:
    """Build a clock positioned at the start of its period.

    The ordinary way to make a clock, mirroring
    :func:`~eds.platform.project.project.create_project`. Constructing
    :class:`SimulationClock` directly is still available and requires the
    current date to be stated, which is what a restore needs.

    Args:
        start: The first day of the simulated period.
        end: The last day, or ``None`` for an open-ended period.
        tick: How far one advancement moves. One day by default.
        calendar: Which days the enterprise is open. Every day, by default -
            a simulation that has not been told about weekends should not
            invent them.

    Returns:
        A clock at ``start``.

    Raises:
        InvalidTimeRangeError: If ``end`` precedes ``start``.
    """
    return SimulationClock(
        time_range=TimeRange(start=start, end=end),
        current_date=start,
        tick=tick,
        calendar=calendar if calendar is not None else ContinuousCalendar(),
    )
