# PADR-012: Runtime Contracts Are Deterministic Facts

**Status:** Accepted (P005.1)

**Builds on:** PADR-008 (plans are inert), PADR-010 (time is a value),
PADR-011 (the run binds the primitives), ADR-005 (deterministic generation).

## Context

P005 settled the scheduler's *input*. Nothing had settled its *output*.

A scheduler that had to invent its own result type would invent one shaped by
how it happened to execute — a mutable accumulator, probably, holding an
exception object and a wall-clock timestamp. Then a growth engine, a snapshot
writer and a change-capture reader would each be coupled to that scheduler
rather than to the platform, and every one of them would be untestable until
the scheduler existed.

Defining the vocabulary first inverts that. The scheduler has nothing left to
invent, its consumers are written against the platform, and the contracts can
be built and tested with nothing executing at all.

## Decision

Eight types, in four groups. Everything is a frozen record of facts.

| Group | Types | Answers |
| --- | --- | --- |
| Status | `ExecutionStatus`, `STATUS_TRANSITIONS` | Where something got to, and where it may go next |
| Outcome | `RunResult`, `StageResult` | What happened |
| Detail | `Failure`, `FailureType`, `ExecutionWarning` | Why, and what else is worth reading |
| Narrative | six `ExecutionEvent`s, `Progress` | How it got there, and how far along it is |

### No contract carries wall-clock time

This is the decision everything else hangs on.

An `ExecutionEvent` stamped with `datetime.now()` cannot be compared, stored as
a fixture, or asserted on. Two runs of the same simulation with the same seed
would produce different results, and the property that makes a result worth
storing — that it *is* the simulation's outcome, not a recording of one
afternoon — would be gone. ADR-005 forbids wall-clock input to generation;
letting it in through the results would give it back through a side door.

So a stage's dates are simulated dates, a run's ticks are the clock's ticks,
`duration_days` is simulated duration, and events order by a monotonic
`sequence` rather than by a timestamp. A test forbids any call to `now()`,
`today()`, `utcnow()`, `sleep()`, `monotonic()` or `perf_counter()` anywhere in
the package.

A scheduler that wants to log elapsed seconds is free to. That is telemetry, and
telemetry is not a contract.

### One status enum — the challenge, answered

The brief proposed `PENDING, RUNNING, COMPLETED, FAILED, SKIPPED, CANCELLED`
and invited a challenge. The objection is real but does not need a different
enum.

**1. Current design.** One enum of six, used by both results and any in-flight
tracking.

**2. The objection.** A *result* is a record of something that finished.
`PENDING` and `RUNNING` describe work in flight, so a `StageResult` carrying
`RUNNING` is a typed value that cannot be true — and every consumer must handle
a case that should never reach it.

**3. The proposal considered.** Two enums: `StageState` for the lifecycle and
`StageStatus` for terminal outcomes only.

**4. Why it was rejected.** It buys the invariant at the price of two
vocabularies, two transition tables, two serialisations and a conversion between
them — for a distinction that one line of validation expresses better.
**Results refuse a non-terminal status at construction.** The invariant is
enforced where it matters and the vocabulary stays single.

**5. Migration impact.** None either way; P005.1 is new.

**6. Recommendation.** Keep one enum, enforce terminality on results. Adopted.

The same reasoning covers the one status a *run* cannot have. A run is never
`SKIPPED` — a stage may be passed over, a run cannot be — and that is one
validation rule rather than a second enum differing by a single member.

Transitions are a **declared table**, not a state machine object. Nothing
advances a status, checks a guard or fires a callback. That is the shape Retail
already uses for `PAYMENT_TRANSITIONS` and `ORDER_TRANSITIONS` (ADR-012), and it
is what keeps this module free of behaviour.

### A failure holds text, not an exception

`Failure.cause` is a string. A traceback survives neither a document nor another
machine, and it pins every local in every frame alive — which in this platform
means a failed stage could hold an entire frame of generated data in memory.
Whatever produced the failure decides how much of the original to render, and
the contract records that rendering as a fact.

`FailureType` follows the four phases a stage actually passes through here —
configure, generate, validate, write — plus `DEPENDENCY` (it never ran because
something upstream failed) and `INTERNAL` (a platform defect). It is derived
from this architecture rather than from a generic severity model, because a
generic taxonomy tells a reader nothing they can act on.

No retries, no recovery, no severity ladder. Whether to retry is a scheduler's
policy, and a policy expressed as a field here is a policy the contract quietly
imposes on everyone.

### Events and results are both needed, and are not redundant

A result answers *what is the state of things now*. The event stream answers
*how did it get there*. The case that proves both are needed: a stage that
started and never finished has a `StageStarted` and **no result at all**,
because a result records something that finished. No aggregate can express that.

The events are a closed set, for P005's reason: a consumer must interpret every
kind, so an open hierarchy would let a producer emit something nothing can read.

**There is no bus.** No emitter, subscriber, observer or dispatch. A scheduler
produces events into a tuple and whatever wants them reads that tuple. Anything
more is transport, and transport is not a contract.

### Contracts cannot contradict themselves

Enforced rather than trusted, because a result that tells two stories is worse
than no result:

* `FAILED` always carries a failure, and a failure always means `FAILED` — both
  directions.
* A skipped or cancelled stage produced no rows.
* A run cannot claim to have `COMPLETED` while holding a stage that failed.
* No stage has two results in one run.
* A result cannot end before it starts, or finish on a tick before it started
  on.
* Progress cannot exceed 100% — that is not optimism, it means the producer is
  counting two different things.

### Percentages are optional

An open-ended run has no total tick count, so its tick percentage is not zero —
it does not exist, and `None` is the only honest answer. A consumer told `0.0`
would render a lie. Likewise `stage_percentage` is `None` for an empty plan:
nought out of nought is not nought per cent.

Four numbers and no more. No throughput, no estimated completion, no rate: a
platform that has never executed anything has no basis for any of them, and a
speculative metric is a number somebody will believe.

### The contracts depend on almost nothing

The only platform import in the package is the date vocabulary from
`eds.platform.time.dates`. A result does not import a plan, a project, a clock
or a run — `run_id`, `project_id` and `stage_id` are opaque strings, the same
discipline P003 used for `completed_stages`.

That is what lets a stored result be read back on a machine where none of those
exist: an analyst reading last quarter's results needs no domain installed. A
test enforces the whole rule, including that no earlier platform module imports
this one.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| **Let the scheduler define its own result** | Every consumer would couple to the scheduler rather than the platform, and none could be built or tested before it. |
| **Two status enums, lifecycle and terminal** | Two vocabularies, two tables, two serialisations and a conversion, to express what one validation rule expresses better. |
| **A separate run status without `SKIPPED`** | A second enum differing by one member is a name without a distinction. |
| **A state machine object with `advance()`** | That is behaviour, and behaviour is the one thing this package may not have. |
| **Wall-clock timestamps on events and results** | Destroys determinism, comparability and every stored fixture, to provide telemetry that belongs in a log. |
| **`Failure` holding the exception** | Not serialisable, and a traceback keeps a frame of generated data alive. |
| **A `severity` field on failures and warnings** | A failure stopped the work and a warning did not; that *is* the severity, and a ladder invites arguing about the middle. |
| **`Warning` as the class name** | Shadows the builtin. `ExecutionWarning` is what a reader of a result calls it, and it is documented as not being a Python warning. |
| **Events only, deriving results by folding the stream** | Every consumer would reimplement the fold, and each slightly differently. |
| **Results only, no events** | Cannot express a stage that started and never finished. |
| **An event bus, emitter or observer** | Transport, not contract. Explicitly a non-goal. |
| **Storing derived percentages in the document** | A stored derived value can disagree with what it was derived from. |
| **A mutable accumulator the scheduler fills in** | The natural thing to reach for, and it makes every intermediate state observable and every consumer defensive. Building the final value once is the whole discipline. |

## Consequences

**Good.** The scheduler has nothing left to invent. It reads a
`SimulationRun` (PADR-011) and writes a `RunResult` and a tuple of
`ExecutionEvent`s, all of which already exist and are tested.

**Good.** Results are comparable, storable and diffable. Two runs of one
simulation produce equal results and equal documents — a test asserts it — which
means a regression in a future scheduler is a diff rather than an investigation.

**Good.** The consumers named in the brief can now be written independently.
Growth reads `RunResult.rows_by_dataset` and `ticks_elapsed`; snapshots read
`start_date`, `end_date` and `stage_ids`; change capture reads the event stream
in sequence. None of them needs the scheduler, and none needs the others.

**Cost.** A fifth interface with no consumer. This is the last of them — the
scheduler is the first component that produces rather than declares — but until
it exists these are contracts nobody has signed.

**Cost.** `Progress` is the one contract with no obvious producer inside the
platform. A scheduler will build it to report to a caller, and until there is a
caller to report to, its shape is the least evidenced thing here.

**Limitation.** No real elapsed time anywhere. An operator wanting to know that
a stage took forty seconds must get that from a scheduler's log, not from the
result. That is the deliberate price of determinism, and the boundary is stated
rather than fudged.

**Limitation.** `rows_by_dataset` assumes a stage's output is countable in rows.
True for every adapter that exists, and it would need revisiting for a target
where "rows written" is not the unit — a stream, say.

**Limitation.** Events carry a sequence a producer must assign correctly. The
contract checks that a sequence is not negative and orders stably by it; it
cannot check that a producer numbered its stream sensibly, because it never sees
the whole stream.

## Future integration

**Scheduler (P006).** `def execute(run: SimulationRun) -> RunResult`, with the
event tuple either alongside or on the result. It uses `require_valid_transition`
to police its own lifecycle tracking, builds one `StageResult` per stage as each
finishes, and assembles the `RunResult` at the end. It never mutates one —
building the final value once is what keeps the contract a fact.

**Growth engine.** Reads `RunResult.rows_by_dataset` for how much an enterprise
grew and `ticks_elapsed` for over how long. Combined with
`SimulationState.last_identifiers`, that is everything a growth curve needs.

**Snapshots.** Read `start_date`, `end_date` and `stage_ids` to know what a
point-in-time copy covers, and `status` to know whether it is worth taking one.
A snapshot of a failed run is a snapshot of an inconsistent state.

**Change capture.** Reads the event stream `in_sequence`. `StageCompleted` is
the natural boundary for a change set: everything a stage produced, at the
simulated date it produced it.

**Persistence.** A `RunResult` round-trips completely, so a project could store
its run history as documents through P003's `StateStore` with no new machinery.
Whether it should is a decision for whichever phase owns run history.

## What this decision does not permit

The contracts must not gain behaviour. A test forbids importing `polars`,
`eds.domains`, `eds.adapters`, `eds.platform.execution`, `eds.platform.project`,
`eds.platform.run`, `threading`, `asyncio` or `logging`, and forbids any
wall-clock call. Nothing here may execute, schedule, retry, dispatch or observe.
If a future phase needs a contract and a behaviour together, the behaviour goes
in the component, not in the contract.
