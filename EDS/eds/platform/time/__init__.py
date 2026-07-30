"""The simulation time model.

This package answers **"what does time mean here?"**. It does not answer "run
the next tick".

It defines the vocabulary later phases will speak: a period
(:class:`~eds.platform.time.time_range.TimeRange`), a unit of advancement
(:class:`~eds.platform.time.tick.Tick`), which days an enterprise is open
(:class:`~eds.platform.time.calendar.Calendar`), and where a simulation has
reached (:class:`~eds.platform.time.clock.SimulationClock`). Everything in it
is an immutable value: advancing produces a new clock rather than changing one.

**Simulated time is not wall-clock time.** Nothing here reads the system clock,
sleeps, starts a thread or schedules a callback. A simulation reaches 2027
because something advanced it, and it does so in microseconds; that is the
whole point, and it is also what keeps a run reproducible (ADR-005, PADR-004).

**Time is platform-owned.** A domain consumes simulated dates - Retail already
does, deriving every timestamp from a parent record - but no domain defines
what a tick is, when the weekend falls, or how far a run has got. A test
enforces that no domain imports this package.

Nothing here executes, schedules, or advances anything by itself (PADR-010).
"""

from eds.platform.time.calendar import (
    MAX_CALENDAR_SEARCH_DAYS,
    BusinessCalendar,
    Calendar,
    ContinuousCalendar,
    add_business_days,
    business_days_between,
    next_business_day,
    previous_business_day,
)
from eds.platform.time.clock import SimulationClock, create_clock
from eds.platform.time.dates import (
    MAX_SIMULATION_DATE,
    MIN_SIMULATION_DATE,
    SimulationDate,
    format_simulation_date,
    parse_simulation_date,
)
from eds.platform.time.errors import (
    CalendarError,
    InvalidAdvancementError,
    InvalidDateError,
    InvalidTickError,
    InvalidTimeRangeError,
    SimulationEndedError,
    TimeError,
    TimeOverflowError,
)
from eds.platform.time.persistence import clock_from_state, state_with_clock
from eds.platform.time.tick import DAILY, MONTHLY, WEEKLY, YEARLY, Tick, TickUnit
from eds.platform.time.time_range import TimeRange

__all__ = [
    "DAILY",
    "MAX_CALENDAR_SEARCH_DAYS",
    "MAX_SIMULATION_DATE",
    "MIN_SIMULATION_DATE",
    "MONTHLY",
    "WEEKLY",
    "YEARLY",
    "BusinessCalendar",
    "Calendar",
    "CalendarError",
    "ContinuousCalendar",
    "InvalidAdvancementError",
    "InvalidDateError",
    "InvalidTickError",
    "InvalidTimeRangeError",
    "SimulationClock",
    "SimulationDate",
    "SimulationEndedError",
    "Tick",
    "TickUnit",
    "TimeError",
    "TimeOverflowError",
    "TimeRange",
    "add_business_days",
    "business_days_between",
    "clock_from_state",
    "create_clock",
    "format_simulation_date",
    "next_business_day",
    "parse_simulation_date",
    "previous_business_day",
    "state_with_clock",
]
