"""Architecture tests for the platform time model (P004).

These tests describe what simulated time *means*, not what a simulation does
with it. Nothing here runs a generator, writes a dataset or schedules
anything - if a test in this module needed a scheduler, the time model would
have grown a responsibility it was explicitly denied.

Four properties get the most attention, because they are the ones later phases
will rely on and the ones easiest to lose quietly: advancement is immutable,
advancement is deterministic, the elapsed tick count is derived rather than
counted, and no domain can see any of it.
"""

from __future__ import annotations

import ast
import importlib
from datetime import date, timedelta
from pathlib import Path

import pytest

from eds.platform.project import SimulationState, create_project
from eds.platform.time import (
    DAILY,
    MAX_CALENDAR_SEARCH_DAYS,
    MAX_SIMULATION_DATE,
    MIN_SIMULATION_DATE,
    MONTHLY,
    WEEKLY,
    YEARLY,
    BusinessCalendar,
    Calendar,
    CalendarError,
    ContinuousCalendar,
    InvalidAdvancementError,
    InvalidDateError,
    InvalidTickError,
    InvalidTimeRangeError,
    SimulationClock,
    SimulationEndedError,
    Tick,
    TickUnit,
    TimeError,
    TimeOverflowError,
    TimeRange,
    add_business_days,
    business_days_between,
    clock_from_state,
    create_clock,
    format_simulation_date,
    next_business_day,
    parse_simulation_date,
    previous_business_day,
    state_with_clock,
)

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
TIME_ROOT = PACKAGE_ROOT / "platform" / "time"

#: A Monday, so weekday arithmetic in the tests reads without counting.
MONDAY = date(2024, 1, 1)

#: A leap year February, for the boundary nobody remembers until it breaks.
LEAP_DAY = date(2024, 2, 29)


@pytest.fixture
def working_week() -> BusinessCalendar:
    """Return a Saturday-Sunday calendar with one holiday."""
    return BusinessCalendar(holidays=frozenset({date(2024, 1, 1)}))


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------


def test_a_simulation_date_is_read_from_iso_text() -> None:
    """The one accepted spelling round-trips."""
    assert parse_simulation_date("2024-03-17") == date(2024, 3, 17)
    assert format_simulation_date(date(2024, 3, 17)) == "2024-03-17"


def test_surrounding_whitespace_is_tolerated() -> None:
    """A value read from a config file may carry indentation."""
    assert parse_simulation_date("  2024-03-17\n") == date(2024, 3, 17)


@pytest.mark.parametrize(
    "text",
    [
        "20240317",  # accepted by date.fromisoformat since 3.11, rejected here
        "2024-W11-7",
        "2024-03-17T00:00:00",
        "17/03/2024",
        "2024-3-17",
        "",
        "not a date",
    ],
)
def test_other_spellings_are_rejected(text: str) -> None:
    """One format, so two config files cannot disagree about what a date is."""
    with pytest.raises(InvalidDateError, match="ISO 8601"):
        parse_simulation_date(text)


def test_a_well_formed_but_impossible_date_is_rejected() -> None:
    """Shape is not the same as existence."""
    with pytest.raises(InvalidDateError, match="not a real date"):
        parse_simulation_date("2023-02-29")


def test_a_non_string_is_rejected_descriptively() -> None:
    """Documents can hold anything, so the parser checks rather than assumes."""
    with pytest.raises(InvalidDateError, match="must be a string"):
        parse_simulation_date(20240317)


def test_the_error_names_the_field() -> None:
    """A range has two dates, so a message that says only 'date' is useless."""
    with pytest.raises(InvalidDateError, match="time range end"):
        parse_simulation_date("nonsense", "time range end")


def test_the_supported_range_is_the_one_dates_have() -> None:
    """No narrower limit is invented."""
    assert date.min == MIN_SIMULATION_DATE
    assert date.max == MAX_SIMULATION_DATE


# --------------------------------------------------------------------------
# Ticks
# --------------------------------------------------------------------------


@pytest.mark.parametrize("size", [0, -1, -100])
def test_a_tick_that_cannot_move_time_is_rejected(size: int) -> None:
    """A zero tick presents as a hang; a negative one rewinds."""
    with pytest.raises(InvalidTickError, match="at least 1"):
        Tick(size, TickUnit.DAY)


@pytest.mark.parametrize("size", [1.5, "1", None, True])
def test_a_non_integer_tick_size_is_rejected(size: object) -> None:
    """Including ``True``, which is an integer only by accident of history."""
    with pytest.raises(InvalidTickError, match="must be an integer"):
        Tick(size, TickUnit.DAY)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("tick", "expected"),
    [
        (Tick(1, TickUnit.DAY), date(2024, 1, 2)),
        (Tick(10, TickUnit.DAY), date(2024, 1, 11)),
        (Tick(1, TickUnit.WEEK), date(2024, 1, 8)),
        (Tick(2, TickUnit.WEEK), date(2024, 1, 15)),
        (Tick(1, TickUnit.MONTH), date(2024, 2, 1)),
        (Tick(1, TickUnit.YEAR), date(2025, 1, 1)),
    ],
)
def test_each_unit_advances_by_its_own_measure(tick: Tick, expected: date) -> None:
    """One tick of each fixed-length unit."""
    assert tick.advance(MONDAY) == expected


def test_a_tick_applied_zero_times_does_not_move() -> None:
    """Zero is a legitimate count, so a caller's loop need not special-case it."""
    assert MONTHLY.advance(MONDAY, 0) == MONDAY


def test_month_advancement_clamps_to_the_shorter_month() -> None:
    """There is no 31 February, and no other answer is defensible."""
    assert MONTHLY.advance(date(2024, 1, 31)) == date(2024, 2, 29)
    assert MONTHLY.advance(date(2023, 1, 31)) == date(2023, 2, 28)
    assert MONTHLY.advance(date(2024, 3, 31)) == date(2024, 4, 30)


def test_month_advancement_does_not_round_trip() -> None:
    """Documented, not accidental: clamping loses the original day.

    The reason the clock anchors advancement to its start rather than stepping
    from wherever it is.
    """
    forward = MONTHLY.advance(date(2024, 1, 31))

    assert forward == date(2024, 2, 29)
    assert MONTHLY.advance(forward, -1) == date(2024, 1, 29)


def test_stepping_month_by_month_is_not_the_same_as_jumping() -> None:
    """The tick's own arithmetic is relative, and relative arithmetic drifts.

    Stated as a test because it is the flaw the clock is designed around: the
    tick reports honestly what relative stepping does, and the clock declines
    to do it.
    """
    start = date(2024, 1, 31)
    stepwise = start
    for _ in range(5):
        stepwise = MONTHLY.advance(stepwise)

    assert stepwise == date(2024, 6, 29)
    assert MONTHLY.advance(start, 5) == date(2024, 6, 30)


def test_month_advancement_crosses_the_year_boundary() -> None:
    """December plus one month is January of the next year."""
    assert MONTHLY.advance(date(2024, 12, 15)) == date(2025, 1, 15)
    assert Tick(13, TickUnit.MONTH).advance(date(2024, 12, 15)) == date(2026, 1, 15)


def test_a_leap_day_advanced_by_a_year_lands_on_the_28th() -> None:
    """2025 has no 29 February."""
    assert YEARLY.advance(LEAP_DAY) == date(2025, 2, 28)


def test_a_leap_day_advanced_by_four_years_lands_on_a_leap_day() -> None:
    """The clamp applies to the target year, not cumulatively."""
    assert Tick(4, TickUnit.YEAR).advance(LEAP_DAY) == date(2028, 2, 29)


def test_a_century_that_is_not_a_leap_year_is_handled() -> None:
    """1900 and 2100 are not leap years; 2000 was."""
    assert YEARLY.advance(date(2096, 2, 29), 4) == date(2100, 2, 28)


def test_advancement_past_the_last_representable_day_overflows() -> None:
    """Reported as a time error, not as a raw arithmetic failure."""
    with pytest.raises(TimeOverflowError, match="dates can represent"):
        DAILY.advance(MAX_SIMULATION_DATE)


def test_month_advancement_past_the_last_year_overflows() -> None:
    """Month arithmetic checks the year rather than trusting the constructor."""
    with pytest.raises(TimeOverflowError, match="years 1 to 9999"):
        MONTHLY.advance(date(9999, 12, 1))


def test_advancement_before_the_first_representable_day_overflows() -> None:
    """The lower bound is a bound too."""
    with pytest.raises(TimeOverflowError, match="dates can represent"):
        DAILY.advance(MIN_SIMULATION_DATE, -1)


def test_a_tick_reads_readably(working_week: BusinessCalendar) -> None:
    """Ticks appear in error messages, so they must pluralise."""
    del working_week
    assert str(DAILY) == "1 day"
    assert str(Tick(3, TickUnit.BUSINESS_DAY)) == "3 business days"


def test_only_business_day_ticks_need_a_calendar() -> None:
    """The one unit whose length is not fixed says so."""
    assert Tick(1, TickUnit.BUSINESS_DAY).needs_calendar
    assert not DAILY.needs_calendar
    assert not MONTHLY.needs_calendar


def test_a_business_day_tick_without_a_calendar_treats_every_day_as_open() -> None:
    """The default is the assumption-free one, not a weekday guess."""
    assert Tick(1, TickUnit.BUSINESS_DAY).advance(date(2024, 1, 6)) == date(2024, 1, 7)


# --------------------------------------------------------------------------
# Elapsed ticks, which are derived rather than counted
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tick", "current", "expected"),
    [
        (DAILY, date(2024, 1, 11), 10),
        (Tick(3, TickUnit.DAY), date(2024, 1, 11), 3),  # 10 days is three whole ticks
        (WEEKLY, date(2024, 1, 15), 2),
        (MONTHLY, date(2024, 4, 1), 3),
        (MONTHLY, date(2024, 3, 31), 2),  # part-way through the third month
        (YEARLY, date(2026, 1, 1), 2),
    ],
)
def test_elapsed_counts_whole_ticks(tick: Tick, current: date, expected: int) -> None:
    """A date part-way through a tick counts only the completed ticks."""
    assert tick.elapsed(MONDAY, current) == expected


def test_elapsed_survives_month_clamping() -> None:
    """The reason the count is probed rather than subtracted.

    One month after 31 January is 29 February, whose day-of-month is lower than
    the start's. Subtracting month numbers would still say one; subtracting
    with a day-of-month correction would say zero. Only probing the actual
    arithmetic gets it right.
    """
    start = date(2024, 1, 31)

    for count in range(1, 13):
        assert MONTHLY.elapsed(start, MONTHLY.advance(start, count)) == count


def test_elapsed_is_the_inverse_of_advance(working_week: BusinessCalendar) -> None:
    """For every unit, advancing n ticks means n ticks have elapsed."""
    ticks = [DAILY, Tick(3, TickUnit.DAY), WEEKLY, MONTHLY, YEARLY, Tick(2, TickUnit.BUSINESS_DAY)]

    for tick in ticks:
        for count in (1, 5, 20):
            reached = tick.advance(MONDAY, count, working_week)
            assert tick.elapsed(MONDAY, reached, working_week) == count, tick


def test_elapsed_is_negative_before_the_start() -> None:
    """The count stays monotonic across the start date rather than flooring at zero."""
    assert DAILY.elapsed(MONDAY, MONDAY - timedelta(days=3)) == -3
    assert MONTHLY.elapsed(MONDAY, date(2023, 11, 1)) == -2


# --------------------------------------------------------------------------
# Calendars
# --------------------------------------------------------------------------


def test_every_day_is_a_business_day_on_a_continuous_calendar() -> None:
    """The default makes no assumption about when anyone is closed."""
    calendar = ContinuousCalendar()

    assert calendar.name == "continuous"
    assert all(calendar.is_business_day(MONDAY + timedelta(days=n)) for n in range(14))


def test_the_default_weekend_is_saturday_and_sunday(working_week: BusinessCalendar) -> None:
    """A convention stated in one place, not an assumption buried in logic."""
    assert working_week.is_business_day(date(2024, 1, 4))
    assert not working_week.is_business_day(date(2024, 1, 6))
    assert not working_week.is_business_day(date(2024, 1, 7))


def test_the_weekend_is_configurable() -> None:
    """A Friday-Saturday weekend is as ordinary as a Saturday-Sunday one."""
    calendar = BusinessCalendar(weekend_days=frozenset({4, 5}), label="gulf")

    assert calendar.name == "gulf"
    assert not calendar.is_business_day(date(2024, 1, 5))
    assert not calendar.is_business_day(date(2024, 1, 6))
    assert calendar.is_business_day(date(2024, 1, 7))


def test_a_plain_set_of_weekend_days_is_accepted() -> None:
    """Normalised on construction, so the record stays hashable."""
    calendar = BusinessCalendar(weekend_days={4, 5})

    assert isinstance(calendar.weekend_days, frozenset)
    assert hash(calendar) == hash(BusinessCalendar(weekend_days=frozenset({4, 5})))


def test_holidays_close_a_business_day(working_week: BusinessCalendar) -> None:
    """New Year's Day 2024 was a Monday."""
    assert not working_week.is_business_day(date(2024, 1, 1))
    assert working_week.is_business_day(date(2024, 1, 2))


def test_no_holiday_list_is_shipped() -> None:
    """A jurisdiction's calendar is data, and data belongs to its simulator."""
    assert BusinessCalendar().holidays == frozenset()


@pytest.mark.parametrize("weekend", [{7}, {-1}, {0, 9}])
def test_an_impossible_weekday_is_rejected(weekend: set[int]) -> None:
    """Monday is 0 and Sunday is 6; anything else is a typo."""
    with pytest.raises(CalendarError, match="0 \\(Monday\\) to 6 \\(Sunday\\)"):
        BusinessCalendar(weekend_days=frozenset(weekend))


def test_a_calendar_with_no_business_day_is_rejected() -> None:
    """Caught at construction, where it reads as a mistake.

    Left alone it would present as a search that never finds anything, which
    is a far worse way to learn about a configuration error.
    """
    with pytest.raises(CalendarError, match="no business day"):
        BusinessCalendar(weekend_days=frozenset(range(7)))


def test_the_next_business_day_skips_the_weekend(working_week: BusinessCalendar) -> None:
    """Friday's next business day is Monday."""
    assert next_business_day(working_week, date(2024, 1, 5)) == date(2024, 1, 8)


def test_the_next_business_day_is_strictly_after(working_week: BusinessCalendar) -> None:
    """A business day's next business day is not itself."""
    assert next_business_day(working_week, date(2024, 1, 3)) == date(2024, 1, 4)


def test_the_previous_business_day_skips_backwards(working_week: BusinessCalendar) -> None:
    """Monday's previous business day is the Friday before."""
    assert previous_business_day(working_week, date(2024, 1, 8)) == date(2024, 1, 5)


def test_business_days_accumulate_across_weekends(working_week: BusinessCalendar) -> None:
    """Five business days from a Wednesday is the Wednesday after."""
    assert add_business_days(working_week, date(2024, 1, 3), 5) == date(2024, 1, 10)


def test_adding_zero_business_days_does_not_move(working_week: BusinessCalendar) -> None:
    """Even from a Sunday: zero means zero, not 'snap to the next open day'."""
    assert add_business_days(working_week, date(2024, 1, 7), 0) == date(2024, 1, 7)


def test_business_days_can_be_subtracted(working_week: BusinessCalendar) -> None:
    """A calendar is a general utility; only the clock refuses to go backwards."""
    assert add_business_days(working_week, date(2024, 1, 10), -5) == date(2024, 1, 3)


def test_counting_business_days_inverts_adding_them(working_week: BusinessCalendar) -> None:
    """The property that makes the elapsed tick count derivable."""
    start = date(2024, 1, 3)

    for count in range(1, 40):
        reached = add_business_days(working_week, start, count)
        assert business_days_between(working_week, start, reached) == count


def test_counting_business_days_is_signed(working_week: BusinessCalendar) -> None:
    """Counting the other way gives the same magnitude with the other sign."""
    assert business_days_between(working_week, date(2024, 1, 10), date(2024, 1, 3)) == -5
    assert business_days_between(working_week, date(2024, 1, 3), date(2024, 1, 3)) == 0


def test_a_search_that_finds_nothing_gives_up_descriptively() -> None:
    """A calendar closed for a decade is a configuration error, not a hang."""

    class _AlwaysClosed:
        """A calendar that passes the constructor checks and still answers no."""

        @property
        def name(self) -> str:
            return "always-closed"

        def is_business_day(self, day: date) -> bool:
            del day
            return False

    with pytest.raises(CalendarError, match=f"within {MAX_CALENDAR_SEARCH_DAYS} days"):
        next_business_day(_AlwaysClosed(), MONDAY)


def test_a_custom_calendar_needs_only_one_method() -> None:
    """The derived operations work on anything satisfying the protocol.

    This is the whole reason the protocol declares one predicate: a
    replacement cannot make its own ``next_business_day`` disagree with its own
    ``is_business_day``, because it does not have one.
    """

    class _MonthEndsOnly:
        """Open only on the first of the month."""

        @property
        def name(self) -> str:
            return "month-starts"

        def is_business_day(self, day: date) -> bool:
            return day.day == 1

    calendar = _MonthEndsOnly()

    assert isinstance(calendar, Calendar)
    assert next_business_day(calendar, date(2024, 1, 15)) == date(2024, 2, 1)
    assert add_business_days(calendar, date(2024, 1, 1), 3) == date(2024, 4, 1)
    assert business_days_between(calendar, date(2024, 1, 1), date(2024, 4, 1)) == 3


# --------------------------------------------------------------------------
# Time ranges
# --------------------------------------------------------------------------


def test_a_range_is_inclusive_at_both_ends() -> None:
    """'Simulate 2024' should not require remembering an off-by-one."""
    year = TimeRange(date(2024, 1, 1), date(2024, 12, 31))

    assert year.contains(date(2024, 1, 1))
    assert year.contains(date(2024, 12, 31))
    assert not year.contains(date(2025, 1, 1))
    assert year.length_in_days == 366


def test_an_open_ended_range_contains_everything_after_its_start() -> None:
    """A simulation that runs until somebody stops it is ordinary."""
    forever = TimeRange(MONDAY)

    assert forever.is_open_ended
    assert forever.length_in_days is None
    assert forever.contains(date(9999, 12, 31))
    assert not forever.contains(date(2023, 12, 31))


def test_a_range_that_ends_before_it_starts_is_rejected() -> None:
    """Almost always the two arguments the wrong way round."""
    with pytest.raises(InvalidTimeRangeError, match="before it starts"):
        TimeRange(date(2024, 12, 31), date(2024, 1, 1))


def test_a_single_day_range_is_allowed() -> None:
    """Start equal to end is one day, not an empty period."""
    assert TimeRange(MONDAY, MONDAY).length_in_days == 1


def test_a_range_reads_readably() -> None:
    """Ranges appear in clock error messages."""
    assert str(TimeRange(MONDAY, date(2024, 12, 31))) == "2024-01-01 to 2024-12-31"
    assert str(TimeRange(MONDAY)) == "2024-01-01 to open"


# --------------------------------------------------------------------------
# The clock
# --------------------------------------------------------------------------


def test_a_clock_starts_where_its_period_does() -> None:
    """The ordinary construction."""
    clock = create_clock(MONDAY, end=date(2024, 12, 31))

    assert clock.current_date == MONDAY
    assert clock.start == MONDAY
    assert clock.end == date(2024, 12, 31)
    assert clock.tick == DAILY
    assert clock.ticks_elapsed == 0
    assert not clock.is_finished


def test_the_default_calendar_assumes_nothing() -> None:
    """A clock not told about weekends does not invent them."""
    clock = create_clock(date(2024, 1, 6))  # a Saturday

    assert isinstance(clock.calendar, ContinuousCalendar)
    assert clock.is_business_day


def test_advancing_returns_a_new_clock_and_leaves_this_one_alone() -> None:
    """The central decision of the module, asserted rather than assumed."""
    clock = create_clock(MONDAY)

    later = clock.advance(5)

    assert later is not clock
    assert later.current_date == date(2024, 1, 6)
    assert clock.current_date == MONDAY, "advancing mutated the original clock"


def test_advancing_is_a_function_of_its_arguments() -> None:
    """Twice from the same clock gives the same answer, which mutation loses."""
    clock = create_clock(MONDAY, tick=WEEKLY)

    assert clock.advance(3) == clock.advance(3)
    assert clock.advance(3).current_date == date(2024, 1, 22)


def test_advancing_step_by_step_matches_advancing_at_once(
    working_week: BusinessCalendar,
) -> None:
    """Why the clock anchors to its start: stepping must equal jumping.

    Run from 31 January, which is the date that breaks the naive
    implementation - relative month stepping reaches 29 June where a single
    five-month advancement reaches 30 June.
    """
    ticks = [DAILY, Tick(3, TickUnit.DAY), WEEKLY, MONTHLY, YEARLY, Tick(2, TickUnit.BUSINESS_DAY)]

    for tick in ticks:
        at_once = create_clock(date(2024, 1, 31), tick=tick, calendar=working_week).advance(5)
        stepwise = create_clock(date(2024, 1, 31), tick=tick, calendar=working_week)
        for _ in range(5):
            stepwise = stepwise.advance()

        assert stepwise == at_once, tick
        assert stepwise.ticks_elapsed == 5, tick


def test_advancing_by_zero_returns_the_same_clock() -> None:
    """Identity, not merely equality, so a caller's loop can be trivial."""
    clock = create_clock(MONDAY)

    assert clock.advance(0) is clock


def test_advancing_backwards_is_refused() -> None:
    """Simulated time is monotonic; rewinding is a different operation."""
    clock = create_clock(MONDAY)

    with pytest.raises(InvalidAdvancementError, match="does not run backwards"):
        clock.advance(-1)


def test_a_clock_can_be_repositioned_to_a_date() -> None:
    """A jump, and the target need not fall on a tick boundary."""
    clock = create_clock(MONDAY, tick=WEEKLY)

    moved = clock.advance_to(date(2024, 1, 10))

    assert moved.current_date == date(2024, 1, 10)
    assert moved.ticks_elapsed == 1, "nine days is one whole week, not two"


def test_repositioning_backwards_is_refused() -> None:
    """Same rule as advancing, with a message that says where it already is."""
    clock = create_clock(MONDAY).advance(10)

    with pytest.raises(InvalidAdvancementError, match="already at 2024-01-11"):
        clock.advance_to(MONDAY)


def test_repositioning_to_the_current_date_returns_the_same_clock() -> None:
    """A no-op is a no-op."""
    clock = create_clock(MONDAY)

    assert clock.advance_to(MONDAY) is clock


def test_a_clock_reaching_its_end_reports_it() -> None:
    """The check a caller's loop makes before advancing."""
    clock = create_clock(MONDAY, end=date(2024, 1, 3)).advance(2)

    assert clock.is_finished
    assert clock.remaining_days() == 0


def test_advancing_past_the_end_is_refused_not_clamped() -> None:
    """Clamping would let a loop spin on a clock that never changes."""
    clock = create_clock(MONDAY, end=date(2024, 1, 3))

    with pytest.raises(SimulationEndedError, match="past the simulated period's end"):
        clock.advance(5)


def test_repositioning_past_the_end_is_refused() -> None:
    """The same rule, by the same code path."""
    clock = create_clock(MONDAY, end=date(2024, 1, 3))

    with pytest.raises(SimulationEndedError, match="past the simulated period's end"):
        clock.advance_to(date(2024, 6, 1))


def test_an_open_ended_clock_never_finishes() -> None:
    """There is nothing to reach."""
    clock = create_clock(MONDAY).advance(10_000)

    assert clock.is_open_ended
    assert not clock.is_finished
    assert clock.remaining_days() is None


def test_a_clock_positioned_outside_its_period_is_rejected() -> None:
    """Neither before the start nor after the end is a position it can be in."""
    period = TimeRange(MONDAY, date(2024, 1, 31))

    with pytest.raises(InvalidTimeRangeError, match="outside the simulated period"):
        SimulationClock(time_range=period, current_date=date(2023, 12, 31))
    with pytest.raises(InvalidTimeRangeError, match="outside the simulated period"):
        SimulationClock(time_range=period, current_date=date(2024, 2, 1))


def test_a_clock_reports_whether_the_enterprise_is_open(
    working_week: BusinessCalendar,
) -> None:
    """The calendar question, asked at the clock's current position."""
    clock = create_clock(date(2024, 1, 5), calendar=working_week)

    assert clock.is_business_day
    assert not clock.advance().is_business_day


def test_a_business_day_clock_steps_over_the_weekend(
    working_week: BusinessCalendar,
) -> None:
    """The calendar supplies the tick's meaning; no tick policy is needed."""
    tick = Tick(1, TickUnit.BUSINESS_DAY)
    clock = create_clock(date(2024, 1, 5), tick=tick, calendar=working_week)

    assert clock.advance().current_date == date(2024, 1, 8)
    assert clock.advance(5).current_date == date(2024, 1, 12)
    assert clock.advance(5).ticks_elapsed == 5


def test_a_clock_reads_readably() -> None:
    """Clocks appear in log lines."""
    clock = create_clock(MONDAY, end=date(2024, 12, 31), tick=WEEKLY)

    assert str(clock) == "2024-01-01 (tick 1 week, of 2024-01-01 to 2024-12-31)"


def test_a_clock_is_a_value() -> None:
    """Two clocks with the same fields are the same clock, and both hash."""
    left = create_clock(MONDAY, end=date(2024, 12, 31), tick=MONTHLY)
    right = create_clock(MONDAY, end=date(2024, 12, 31), tick=MONTHLY)

    assert left == right
    assert len({left, right}) == 1


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------


def test_a_tick_round_trips_through_a_document() -> None:
    """The form a future run configuration would be stored in."""
    tick = Tick(3, TickUnit.BUSINESS_DAY)

    assert tick.to_document() == {"size": 3, "unit": "business_day"}
    assert Tick.from_document(tick.to_document()) == tick


@pytest.mark.parametrize("unit", list(TickUnit))
def test_every_unit_survives_a_round_trip(unit: TickUnit) -> None:
    """Including any added later, since the parametrisation is the enum."""
    tick = Tick(2, unit)

    assert Tick.from_document(tick.to_document()) == tick


def test_an_unknown_tick_unit_is_rejected_with_the_known_ones() -> None:
    """The message says what would have worked."""
    with pytest.raises(InvalidTickError, match="is not one of"):
        Tick.from_document({"size": 1, "unit": "fortnight"})


def test_a_corrupt_tick_size_is_rejected() -> None:
    """A document can hold anything."""
    with pytest.raises(InvalidTickError, match="must be an integer"):
        Tick.from_document({"size": "1", "unit": "day"})


def test_a_range_round_trips_through_a_document() -> None:
    """Both the closed and the open-ended case."""
    closed = TimeRange(MONDAY, date(2024, 12, 31))
    open_ended = TimeRange(MONDAY)

    assert closed.to_document() == {"start": "2024-01-01", "end": "2024-12-31"}
    assert open_ended.to_document() == {"start": "2024-01-01", "end": None}
    assert TimeRange.from_document(closed.to_document()) == closed
    assert TimeRange.from_document(open_ended.to_document()) == open_ended


def test_a_corrupt_range_document_is_rejected() -> None:
    """Validation applies to what was read, not only to what was constructed."""
    with pytest.raises(InvalidDateError, match="time range start"):
        TimeRange.from_document({"start": "yesterday", "end": None})
    with pytest.raises(InvalidTimeRangeError, match="before it starts"):
        TimeRange.from_document({"start": "2024-12-31", "end": "2024-01-01"})


def test_a_calendar_round_trips_through_a_document(working_week: BusinessCalendar) -> None:
    """Sorted, so the same calendar always produces the same document."""
    document = working_week.to_document()

    assert document == {
        "kind": "business",
        "label": "business",
        "weekend_days": [5, 6],
        "holidays": ["2024-01-01"],
    }
    assert BusinessCalendar.from_document(document) == working_week


def test_documents_are_stable_across_repeated_rendering() -> None:
    """Set iteration order must not reach a stored document."""
    calendar = BusinessCalendar(
        weekend_days=frozenset({6, 5}),
        holidays=frozenset({date(2024, 12, 25), date(2024, 1, 1)}),
    )

    assert calendar.to_document() == calendar.to_document()
    assert calendar.to_document()["holidays"] == ["2024-01-01", "2024-12-25"]


def test_a_continuous_calendar_serialises_to_its_kind() -> None:
    """It has no configuration, so its document says only what it is."""
    assert ContinuousCalendar().to_document() == {"kind": "continuous"}


@pytest.mark.parametrize(
    "document",
    [
        {"weekend_days": "56"},
        {"weekend_days": [5, "6"]},
        {"weekend_days": [5, 6], "holidays": "2024-01-01"},
        {"weekend_days": [5, 6], "label": 7},
    ],
)
def test_a_corrupt_calendar_document_is_rejected(document: dict[str, object]) -> None:
    """Each field is checked, because a stored document can hold anything."""
    with pytest.raises(CalendarError):
        BusinessCalendar.from_document(document)


# --------------------------------------------------------------------------
# Project integration
# --------------------------------------------------------------------------


def test_a_clock_restores_to_the_start_when_a_project_has_never_run() -> None:
    """No simulated date is not an error; it means nothing has happened yet."""
    clock = clock_from_state(SimulationState(), TimeRange(MONDAY, date(2024, 12, 31)))

    assert clock.current_date == MONDAY
    assert clock.ticks_elapsed == 0


def test_a_clock_resumes_exactly_where_state_says() -> None:
    """The property the derived tick count exists to provide."""
    period = TimeRange(MONDAY, date(2024, 12, 31))
    ran = create_clock(MONDAY, end=date(2024, 12, 31), tick=WEEKLY).advance(6)

    restored = clock_from_state(state_with_clock(SimulationState(), ran), period, tick=WEEKLY)

    assert restored == ran
    assert restored.ticks_elapsed == ran.ticks_elapsed == 6


def test_recording_a_clock_leaves_the_original_state_alone() -> None:
    """State is replaced, never mutated - the same bargain the clock makes."""
    before = SimulationState(completed_stages=("retail:master-data",))

    after = state_with_clock(before, create_clock(MONDAY).advance(3))

    assert before.current_date is None
    assert after.current_date == date(2024, 1, 4)
    assert after.completed_stages == before.completed_stages


def test_a_persisted_date_outside_the_period_is_reported() -> None:
    """State and period disagreeing about what is simulated is worth raising."""
    state = SimulationState(current_date=date(2030, 1, 1))

    with pytest.raises(InvalidTimeRangeError, match="outside the simulated period"):
        clock_from_state(state, TimeRange(MONDAY, date(2024, 12, 31)))


def test_a_clock_survives_a_full_project_round_trip(tmp_path: Path) -> None:
    """The lifecycle a scheduler will drive: run, persist, reopen, resume.

    Written against a real project rather than a state object, because the
    claim being tested is that the two models fit together without either
    being changed.
    """
    project = create_project(tmp_path / "shop", name="Shop", domain="retail", seed=42)
    period = TimeRange(MONDAY, date(2024, 12, 31))

    clock = create_clock(MONDAY, end=date(2024, 12, 31), tick=MONTHLY).advance(4)
    project.write_state(state_with_clock(project.read_state(), clock))

    resumed = clock_from_state(project.read_state(), period, tick=MONTHLY)

    assert resumed.current_date == date(2024, 5, 1)
    assert resumed.ticks_elapsed == 4
    assert resumed.advance().current_date == date(2024, 6, 1)


# --------------------------------------------------------------------------
# Architectural constraints
# --------------------------------------------------------------------------


def test_no_domain_knows_about_simulated_time() -> None:
    """Domains consume dates; they do not define what a tick is."""
    for source in (PACKAGE_ROOT / "domains").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "eds.platform.time" not in text, f"{source.name} reaches into the time model"


def test_the_time_model_introduces_no_runtime() -> None:
    """P004 defines time; it does not run, sleep, thread or schedule."""
    banned = (
        "polars",
        "eds.domains",
        "eds.adapters",
        "eds.platform.execution",
        "threading",
        "asyncio",
    )
    for source in TIME_ROOT.rglob("*.py"):
        for imported in _imported_modules(source):
            assert not imported.startswith(banned), f"{source.name} imports {imported}"


def test_the_time_model_never_reads_the_wall_clock() -> None:
    """Simulated time is not wall-clock time, and no shortcut may blur them.

    A single ``datetime.now()`` anywhere in this package would make a
    simulation's output depend on when it was run, which is the one property
    the platform will not trade (ADR-005).
    """
    banned = ("now", "today", "utcnow", "sleep", "monotonic", "perf_counter", "time")
    for source in TIME_ROOT.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in banned, f"{source.name} calls {node.func.attr}()"


def test_only_the_bridge_module_knows_that_projects_exist() -> None:
    """The time model proper depends on nothing but the standard library.

    Checked against imports rather than text, because a docstring may name
    :mod:`eds.platform.project` to explain the relationship without creating
    one.
    """
    for source in TIME_ROOT.rglob("*.py"):
        if source.name in {"persistence.py", "__init__.py"}:
            continue
        for imported in _imported_modules(source):
            assert not imported.startswith("eds.platform.project"), (
                f"{source.name} imports {imported}"
            )


def _imported_modules(source: Path) -> list[str]:
    """Return every module name a source file imports.

    Args:
        source: The file to read.

    Returns:
        The imported module names, from both import forms.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    return names


@pytest.mark.parametrize("package", ["project", "execution"])
def test_the_earlier_platform_modules_do_not_depend_on_time(package: str) -> None:
    """P002 and P003 are frozen: the dependency runs one way, and only one way.

    A plan says what runs and a project says what has run; the clock says when.
    Joining any of them is a scheduler's job, and the scheduler does not exist.
    """
    for source in (PACKAGE_ROOT / "platform" / package).rglob("*.py"):
        for imported in _imported_modules(source):
            assert not imported.startswith("eds.platform.time"), f"{source.name} imports {imported}"


def test_every_time_error_is_a_value_error() -> None:
    """So a caller validating input need not know this module exists."""
    errors = [
        CalendarError,
        InvalidAdvancementError,
        InvalidDateError,
        InvalidTickError,
        InvalidTimeRangeError,
        SimulationEndedError,
        TimeOverflowError,
    ]

    assert all(issubclass(error, TimeError) for error in errors)
    assert issubclass(TimeError, ValueError)


@pytest.mark.parametrize(
    "name",
    [
        "eds.platform.time",
        "eds.platform.time.calendar",
        "eds.platform.time.clock",
        "eds.platform.time.dates",
        "eds.platform.time.errors",
        "eds.platform.time.persistence",
        "eds.platform.time.tick",
        "eds.platform.time.time_range",
    ],
)
def test_time_modules_are_importable_and_documented(name: str) -> None:
    """Every module in the package imports cleanly and states its purpose."""
    module = importlib.import_module(name)

    assert module.__doc__ is not None
    assert module.__doc__.strip()
