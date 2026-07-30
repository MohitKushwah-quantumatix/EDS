# PADR-010: Simulated Time Is a Value, and the Platform Owns It

**Status:** Accepted (P004)

**Supersedes:** the `eds/platform/clock.py` placeholder declared in P001.

**Builds on:** PADR-004 (platform owns lifecycle), PADR-008 (plans are inert),
PADR-009 (the project stores, it does not run), ADR-005 (deterministic
generation).

## Context

P001 declared `eds/platform/clock.py` as an empty module so that the eventual
owner of simulated time would visibly be the platform rather than any one
domain. P003 stored `current_date` in `SimulationState` and said, in as many
words, that advancing it was the clock's job — a job with no implementation.

P004 defines what time *means* so that a scheduler, a growth engine and a
runtime can be built against a vocabulary that already exists. It defines only
that. Nothing in it runs, sleeps, schedules or advances anything by itself.

## Decision

Six concepts, all immutable values.

| Concept | Owns | Notes |
| --- | --- | --- |
| `SimulationDate` | A day in simulated time | An **alias** for `datetime.date`, not a wrapper |
| `TimeRange` | The declared period | Inclusive both ends; the end is optional |
| `Tick` | One logical advancement | Size plus unit; pure data plus arithmetic |
| `Calendar` | Which days an enterprise is open | A protocol with **one** method |
| `SimulationClock` | Where a simulation has reached | Advancing returns a new clock |
| `clock_from_state` / `state_with_clock` | The bridge to P003 | The only module that knows projects exist |

### The clock is immutable — the review question, answered

The specification asked whether `SimulationClock` should be mutable or whether
advancement should produce a new instance. It produces a new instance, for four
reasons in increasing order of weight.

1. **It would be the platform's only mutable thing.** `ExecutionPlan`,
   `PlannedStage`, `ProjectManifest`, `SimulationState`, `Workspace` and
   `Project` are all frozen records. A mutable clock is an exception a reader
   has to carry.
2. **Advancement would stop being a function.** `clock.advance(5)` twice would
   give two different answers, so a clock that was read, logged or compared
   could not be trusted to still mean what it said.
3. **A mutable clock is shared hidden state.** Two components holding one see
   each other's advancement. PADR-004 requires a run to remain a pure function
   of `(project, seed, upstream data)`; passing time by value keeps that
   mechanical rather than a matter of discipline.
4. **It would disagree with the state model.** P003's `SimulationState` is
   frozen and replaced. If state is replaced while the clock is mutated, the
   two drift apart in the way that is hardest to notice. As values, they
   cannot.

The cost is real: a caller must rebind, and a dropped `clock.advance()` is a
silent no-op. That is the bargain `datetime.date` and `pathlib.Path` already
make, so at least it is a familiar one.

### The calendar is an independent strategy — the second review question

The specification also asked whether `BusinessCalendar` belongs inside the
clock. It does not. The clock **holds** a calendar, injected at construction,
and asks it one question.

Building weekends into the clock would make every simulated enterprise a
five-day one. Building a calendar *hierarchy* into it would make the clock the
place regional holiday rules accumulate. A clock that consults a calendar can
be given a different one; a clock that *is* a calendar cannot.

The protocol declares exactly one method — `is_business_day(day)`. Everything
else (`next_business_day`, `previous_business_day`, `add_business_days`,
`business_days_between`) is a module-level function derived from that
predicate. Had the protocol declared six methods, every replacement would have
to implement six, and any one could contradict the other five: a calendar whose
`next_business_day` returned a day its own `is_business_day` rejects is a bug
no type checker would catch. With one method there is nothing to keep
consistent. A test builds a calendar open only on the first of each month, and
all four derived operations work on it unchanged.

No country is assumed. The weekend is a configurable set of weekday numbers —
a Friday–Saturday weekend is as ordinary as a Saturday–Sunday one — and this
module ships no holiday list and never will. A jurisdiction's calendar is data,
and data belongs to whoever simulates that jurisdiction. The **default** is
`ContinuousCalendar`, on which every day is a business day: a clock that has
not been told about weekends should not invent them.

### There is no `TickPolicy`

The suggested design has a policy object deciding which days a tick may land
on. In practice that is one question — does this tick skip non-business days? —
and it already has an owner. `BUSINESS_DAY` is a unit like any other, and the
calendar supplies its meaning. Three business days is
`Tick(3, TickUnit.BUSINESS_DAY)`. A policy object would have been a third
collaborator whose entire content was a flag.

### `SimulationDate` is an alias, not a wrapper

A wrapper type would buy nothing: `datetime.date` is already immutable,
ordered, hashable and serialisable. It would cost a conversion at every
boundary — P003 already stores `current_date` as a `date`, Retail's generators
already work in `date`, and Polars already has a date type. Wrapping would put
a translation layer between three things that already agree, and would have
forced a change to frozen P003 code.

What the alias buys is a name: `SimulationDate` in a signature says *simulated*
time rather than wall-clock time, which is the distinction that matters.

Parsing is stricter than `date.fromisoformat`, which since Python 3.11 also
accepts `"20240101"`, `"2024-W01-1"` and full timestamps. One spelling —
`YYYY-MM-DD` — so two configuration files cannot disagree about what a date is.

### The elapsed tick count is derived, never stored

A stored counter would be wrong the moment a clock was restored from a
persisted date, because P003 stores the date and not the count, and month
arithmetic clamps so it could not be recovered by subtraction either. Deriving
it from `(start, tick, calendar, current_date)` means a restored clock and a
ticked one always agree — which is exactly what resumption needs, and it needed
no change to P003 to get it.

### A tick is a grid, not a step

**This was found by a test, not by design.** Month arithmetic is not
associative under clamping: five single-month advancements from 31 January
reach 29 June, while one five-month advancement reaches 30 June. Under relative
stepping the clock would also report *four* elapsed ticks after five
`advance()` calls, because the derived count probes the arithmetic that
actually happened.

So advancement is measured from the period's **start**, not from wherever the
clock happens to be. The tick defines a grid — `start`, `start + 1 tick`,
`start + 2 ticks` — and the clock moves along it. Stepping, jumping and
restoring then all land on the same dates, and the derived count cannot drift.
`advance_to(target)` is a reposition rather than a sequence of ticks, and the
target need not be tick-aligned; nothing drifts, because the count is derived
and reports completed ticks.

### Refusing rather than clamping

Advancing past a declared end raises `SimulationEndedError`. Clamping would let
a caller's loop spin forever on a clock that never changes; running past it
silently would produce data outside the period that was asked for. Advancing
backwards raises too — simulated time is monotonic, and rewinding is a
different operation nothing has asked for. Constructing an earlier clock is
always available and is explicit.

Every error inherits from `ValueError`, so a caller validating input need not
know this module exists, and the platform's convention that a frozen record
rejects a bad field with a `ValueError` stays intact.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| **Mutable clock with in-place `advance()`** | Four reasons above; the decisive one is that PADR-004's purity requirement becomes a matter of discipline rather than of type. |
| **Calendar owned by the clock** | Makes every enterprise five-day, and makes the clock where holiday rules accumulate. |
| **Six-method `Calendar` protocol** | Every replacement must implement six operations that can silently contradict each other. |
| **`TickPolicy` strategy object** | A third collaborator whose whole content is one flag the calendar already owns. |
| **`SimulationDate` as a wrapper type** | A conversion boundary between three layers that already agree on `datetime.date`, and a change to frozen P003 code. |
| **Relative advancement from the current date** | Month clamping makes it non-associative, and the derived tick count disagrees with the number of advancements made. |
| **Stored tick counter** | Cannot survive restoration from a persisted date, and cannot be recomputed by subtraction under clamping. |
| **`TimeProvider` indirection** | An injection point for *what supplies the time*. There is nothing to inject: the clock is a value, and a test that wants a different date constructs one. Suggested in the brief, and only "if justified" — it is not. |
| **Clamping at the end of the range** | A loop on a clock that never changes, presenting as a hang. |
| **Serialising the whole clock** | Would require the `Calendar` protocol to be serialisable, which forces every implementer to be. `Tick`, `TimeRange` and both concrete calendars serialise; a custom calendar is its author's problem until something needs otherwise. |
| **Half-open `TimeRange`** | "Simulate 2024" should not require remembering whether 31 December is in. |
| **A `SimulationTime` type separate from the clock** | The clock is already a value; a second value describing the same thing is a name without a distinction. |

## Consequences

**Good.** P001's last substantive placeholder is replaced by a real
implementation with a documented reason, and P003 needed no change to accept
it: `state_with_clock` and `clock_from_state` are ordinary functions over the
existing frozen state. That the state model absorbed a clock without
modification is the strongest available evidence that PADR-009 drew it
correctly.

**Good.** The time model proper depends on nothing but the standard library. A
test enforces that only `persistence.py` knows projects exist, that no domain
imports the package at all, and that no module in it ever calls `now()`,
`today()` or `sleep()` — a single wall-clock read would make output depend on
when a run happened, which is the one property the platform will not trade.

**Cost.** Nothing consumes a clock yet, which is now the third platform
interface awaiting its first caller — after the execution plan and the project.
That is the shape of building a platform bottom-up, and the risk it carries is
that all three meet for the first time in the scheduler.

**Cost.** `eds/platform/clock.py` was deleted rather than kept as a shim.
PADR-005 protects the *pre-platform public API*; a placeholder whose own
docstring said "nothing imports this module" is not part of it. One
architecture test was updated to match.

**Limitation.** Anchoring advancement to the start means each `advance()`
recomputes the elapsed count. For day, week, month and year ticks that is
arithmetic. For business-day ticks it walks the calendar day by day, because
the one-method protocol deliberately hides whatever structure would allow a
closed form — so a long business-day simulation is quadratic in its length. A
year of business days is a few hundred thousand predicate calls, which is
nothing; a decade is noticeable. The fix, when something needs it, is an
optional fast path on calendars that can offer one, not a change to the
protocol every calendar must satisfy.

**Limitation.** A calendar is not persisted with a project. `Tick`, `TimeRange`
and both concrete calendars render to documents, but which calendar a run used
is not recorded anywhere, so a resumed run could in principle be given a
different one. Recording it belongs with whichever phase gives a run its
configuration, and no such phase exists.

**Limitation.** Holidays are a flat set of dates. Recurring rules — "the fourth
Thursday of November", "Easter Monday" — would need a rule type. A caller can
expand rules into dates today, and the protocol accommodates any calendar that
can answer the predicate.

## Future integration

**Scheduler.** Takes a `Project`, an `ExecutionPlan` and a `SimulationClock`.
The plan says *what* runs and in what order; the clock says *when*; the project
says what has already run. The scheduler is the component that joins all three,
and a test asserts that none of them depends on the others — a plan needs no
clock, a clock needs no plan, and neither needs a project. A daily simulation
is the same plan executed once per tick:

```python
while not clock.is_finished:
    run(plan, clock.current_date)  # the scheduler's job
    clock = clock.advance()  # rebind: the clock is a value
    project.write_state(state_with_clock(project.read_state(), clock))
```

**Growth engine.** Consumes `ticks_elapsed` and `TimeRange.length_in_days` to
decide how much an enterprise has grown by a given point, and
`state.last_identifiers` to continue numbering. Because the tick count is
derived, growth computed at a date is the same whether the run reached it in
one jump or a thousand ticks — which is what makes a growth curve
reproducible.

**Retail and future domains.** Unchanged, and deliberately. Every Retail
timestamp is derived from a parent record — a session's start, an order's
creation, a shipment's delivery — and that stays true. When a run is given a
clock, the clock supplies the *origin* those chains hang from; it does not
replace them. No domain imports this package, and a test enforces it.

**Change tracking.** SCD and CDC need a notion of "slowly", which is what a
tick provides. They remain out of scope.

## What this decision does not permit

The time model must not gain the ability to run anything. A test forbids it
importing `polars`, `eds.domains`, `eds.adapters`, `eds.platform.execution`,
`threading` or `asyncio`, and forbids any call to `now()`, `today()`,
`utcnow()`, `sleep()`, `monotonic()` or `perf_counter()`. If a future phase
needs time and execution together, that belongs in a scheduler that depends on
both, not in either one.
