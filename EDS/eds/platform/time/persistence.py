"""The bridge between simulated time and durable project state.

**This is the only module in the time model that knows P003 exists.** The
clock, the tick, the calendar and the range depend on nothing but
:mod:`datetime`; a test enforces it. Persistence is a separate concern, so it
gets a separate module, and the dependency runs one way only - time reads and
writes project state, and no project module imports the time model.

That direction matters. P003 stores ``current_date`` and says, in as many
words, that advancing it is the clock's job. The clock is now here, and it
still does not belong *inside* the project: a project that could advance itself
would be a project that runs, which is what PADR-009 refused.

Neither function writes anything. :func:`state_with_clock` returns a new state,
which the caller persists through ``Project.write_state``, because deciding
*when* to write is the caller's judgement and not a side effect worth hiding.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from eds.platform.project.state import SimulationState
from eds.platform.time.calendar import Calendar, ContinuousCalendar
from eds.platform.time.clock import SimulationClock
from eds.platform.time.tick import DAILY, Tick
from eds.platform.time.time_range import TimeRange

__all__ = ["clock_from_state", "state_with_clock"]


def clock_from_state(
    state: SimulationState,
    time_range: TimeRange,
    tick: Tick = DAILY,
    calendar: Calendar | None = None,
) -> SimulationClock:
    """Restore a clock from a project's persisted state.

    A project that has never run has no simulated date, and the clock starts
    at the beginning of its period. A project that has run resumes exactly
    where it stopped - :attr:`~eds.platform.time.clock.SimulationClock.ticks_elapsed`
    is derived, so the restored clock reports the same elapsed ticks as the one
    that wrote the date.

    The period, the tick and the calendar are supplied rather than stored,
    because they describe *how a run is configured* rather than what a project
    has done. Persisting them is a decision for whichever phase gives a run its
    configuration, and no such phase exists yet.

    Args:
        state: The project's persisted state.
        time_range: The period being simulated.
        tick: How far one advancement moves.
        calendar: Which days the enterprise is open.

    Returns:
        A clock at the persisted date, or at the period's start if there is
        none.

    Raises:
        InvalidTimeRangeError: If the persisted date lies outside the period,
            which means the state and the period disagree about what is being
            simulated.
    """
    current: date = state.current_date if state.current_date is not None else time_range.start
    return SimulationClock(
        time_range=time_range,
        current_date=current,
        tick=tick,
        calendar=calendar if calendar is not None else ContinuousCalendar(),
    )


def state_with_clock(state: SimulationState, clock: SimulationClock) -> SimulationState:
    """Return state carrying a clock's current date.

    Args:
        state: The state to update.
        clock: The clock whose position should be recorded.

    Returns:
        A new state. The original is unchanged, and nothing is written -
        persisting it is the caller's decision.
    """
    return replace(state, current_date=clock.current_date)
