# PADR-013: The Scheduler Coordinates, and the Executor Arrives as an Argument

**Status:** Accepted (P006)

**Builds on:** PADR-006 (the domain protocol describes, it does not execute),
PADR-008 (plans are inert), PADR-009 (the project stores), PADR-010 (time is a
value), PADR-011 (the run binds), PADR-012 (contracts are facts).

## Context

Five phases declared. P006 is the first that does anything, and the first that
could discover the earlier five were wrong.

They were not. The scheduler is 171 statements, it required no change to any
frozen module, and every decision it did not have to make is a decision an
earlier phase already made: the plan is ordered so there is no sorting, the
clock returns a new clock so there is no time state to protect, the project
owns persistence so there is no serialisation, and the contracts refuse to
contradict themselves so there is no consistency checking.

One thing did not fall out, and it is the central finding of P006.

## The scheduler has nothing to call

PADR-006 removed `generate()` from `SimulationDomain` on evidence: Retail does
not generate in one call, it generates in ordered stages that read what earlier
stages wrote, and a no-argument `generate()` could only be implemented by
duplicating the CLI's orchestration inside the domain. The protocol describes;
it does not execute.

That decision was right and it is still right. It also means the first
executable component in the platform has no way to execute anything.

Three ways out:

| Option | Cost |
| --- | --- |
| Scheduler imports a domain | The platform knows about Retail. Breaks PADR-002, the reason the platform exists. |
| Add `execute()` to `SimulationDomain` | Changes a frozen module, and reopens a question P001.1 closed with evidence rather than opinion. |
| **Executor arrives as an argument** | One protocol with one method, and every existing decision intact. |

**Decision: the executor is a parameter.** `execute(run, executor)`. The
scheduler orchestrates and knows nothing about business; whoever supplies the
executor knows about business and nothing about orchestration; the seam is
`StageExecutor`, which has one method.

The dividend is immediate: **every behaviour in P006 is tested with a fake
executor.** Sixty-three tests execute whole runs — multi-tick, resumed, failed,
targeted, rehearsed — without generating a row, and the scheduler cannot tell
the difference. A scheduler that imported a domain could not have been tested
that way.

The gap this leaves is real and named below: nothing supplies a *Retail*
executor yet.

## Decisions made

### Executors raise; the scheduler classifies

A generator that hits a bad row raises. Requiring every executor to catch
everything and return a `Failure` would push error handling into each of them
and make forgetting it silent. `StageExecutionError` carries the classification
only the executor can make — generation, validation, persistence — and anything
else becomes `FailureType.INTERNAL`, because an exception the platform cannot
name is a defect rather than a condition.

### State is written after a stage succeeds, and at no other time

If a partially-run stage were recorded, a resume would skip work that never
finished and the datasets would be silently short. If a failed stage were
recorded, the failure would be forgotten. Recording only what finished means
the project's state is always a true statement about what exists — which is
what makes a failed run resumable rather than ambiguous. A test drives exactly
this: fail at stage three, then resume, and the two stages that succeeded are
not redone.

### The clock advances between ticks and never within one

Every stage in a tick shares one simulated date, which is what makes a tick a
moment rather than a sequence of them. The clock advances only when another
tick will follow, so the last state written always carries the date the work
was done on and no extra write is needed to correct it.

### A multi-tick run produces one result per stage, spanning the ticks

PADR-012 refuses two results for one stage in a run. That is not an obstacle,
it is the answer: a stage that ran on three ticks gets one `StageResult` whose
`start_date` is the first tick, `end_date` the last, and rows summed. **That is
what a stage result's two dates were for.** The per-tick detail lives in the
event stream, which is exactly PADR-012's split — the result is the state now,
the stream is how it got there.

### Cancelled stages are recorded

A run that stopped early leaves stages behind. Recording them `CANCELLED` keeps
the result total, so a consumer asking what happened to any planned stage gets
an answer instead of a `KeyError`. `PENDING → CANCELLED` is the transition the
status model already declares for exactly this. They emit no events, because
they never started.

### A failure returns; it does not raise

A failed run is an outcome. Raising would give callers two ways to ask one
question and force both paths on everyone.

## The architectural challenges the brief anticipated

**Should `RunStarted` happen before validation?** No. `RunStarted` asserts a
run began, and a run that fails validation never began. A refused run's stream
is `(RunFailed,)` alone. That is unusual to read and it is the truth; the
alternative — announcing a start that did not happen so the stream looks tidy —
makes the first event a false one, in a package whose entire thesis is that
events are facts.

**When exactly should the clock advance?** Between ticks, never within one, and
only when another tick will follow. See above.

**Should zero executed stages produce `RunCompleted`?** Yes — nothing was
asked for and nothing failed. In practice it is unreachable through
`create_run`, which already refuses an empty plan and a resume with nothing
outstanding (PADR-011).

**Should a dry run emit completed events?** **No**, and this is the sharpest of
the four. `StageCompleted` is what change capture will read as a change
boundary. Emitting one for work that did not happen would put a change boundary
where nothing changed — a concrete harm, not a tidiness question. A dry run
emits `RunStarted` and `RunCompleted`, records every stage `SKIPPED`, and adds
a run-level `dry_run` warning so a rehearsal is not mistaken for a
fully-resumed run.

**A dry run makes exactly one pass**, whatever the period. The answer to "what
would run" is the same on every tick, so 365 of them would be noise.

**And the dry-run question P005 left open is now settled by construction.** The
scheduler does not call the executor at all. A guarantee of "no adapters are
called" that depended on every executor implementing it correctly would not be
a guarantee; this one is structural. `SKIPPED` also forbids rows, so PADR-012
mechanically enforces that a rehearsal produced nothing.

## Challenges raised against earlier modules

Neither was silently changed. Both are recorded as limitations.

### 1. `completed_stages` cannot express "completed at tick N"

P003's `SimulationState` records which stages have completed, and refuses a
stage recorded twice. Across a multi-tick run every stage completes on every
tick, so the scheduler records each **once**, the first time — the record
answers "has this ever completed", which is what a resume needs.

The limitation is at the edge: a resume of a run that was interrupted on tick
40 will, on its first tick, skip stages recorded as complete on tick 1. For a
single-tick run — everything that exists today — the behaviour is exactly
right. For a genuinely long multi-tick run interrupted mid-way, resumption is
coarser than it should be.

The fix is a P003 change (recording completion against a date, or state
becoming per-tick), and it should be made when something runs long enough to
need it, not speculatively.

### 2. `started_tick` and `finished_tick` are positions, not counts

`RunResult.ticks_elapsed` is `finished_tick - started_tick`, which measures how
far the *clock* moved. A single-tick run reports zero, because the clock did
not move. Each number is individually true and the pair is consistent with the
clock, whose `ticks_elapsed` is derived from its date. How many ticks were
*executed* is `Progress.completed_ticks`, which the scheduler reports
separately.

Not a defect, but a subtlety worth stating: the two fields answer "where", not
"how much".

### 3. `Progress.completed_stages` — a wording question

PADR-012 describes it as stages that "reached a terminal status". Every stage
in a finished result has reached one, which would make the field always equal
the total. The scheduler reports **successful or skipped** stages instead,
which is the only reading that makes a proportion mean anything. A docstring
question, not a contract change.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| **Scheduler imports the domain registry and calls generators** | The platform would know about Retail. The whole point of P001 was that it does not. |
| **Restore `execute()` on `SimulationDomain`** | Changes a frozen module and reopens a decision made on evidence. |
| **A `Scheduler` class with configuration** | It holds nothing between calls. A class with no state is a namespace with extra steps — the reasoning that made the planner functions (PADR-008). |
| **Raise on failure** | Two ways to ask one question, and both forced on every caller. |
| **Persist after every stage attempt** | A resume would skip work that never finished. |
| **Persist once at the end** | An interrupted run would lose everything it did. |
| **Advance the clock per stage** | A tick would stop being a moment, and stages in one pass would disagree about the date. |
| **Emit `StageCompleted` on a dry run** | Puts a change boundary where nothing changed. |
| **Let the executor decide what a dry run does** | A guarantee that depends on every implementer is not a guarantee. |
| **Add events and progress to `RunResult`** | Editing a frozen module to suit its first consumer — precisely what P006 was told not to do. `ExecutionReport` costs one small container and defines no contract. |
| **Omit cancelled stages from the result** | A consumer asking what happened to a planned stage would get a `KeyError`. |
| **Parallel execution within a dependency level** | An explicit non-goal, and unnecessary: the plan already says which stages may overlap, so it layers on later without touching anything else. |

## Consequences

**Good.** Five phases of declared architecture survived contact with execution
without a single change. That is the strongest evidence available that
P002–P005.1 were drawn correctly, and it was not guaranteed.

**Good.** The scheduler is small enough that a test asserts it. If orchestration
grows past 220 statements, the growth is almost certainly a responsibility
belonging to another module, and that test is where the conversation starts.

**Good.** Determinism is structural rather than maintained. The scheduler reads
no wall clock, holds no randomness, and assigns sequence numbers in emission
order — which is deterministic because execution is sequential. Two executions
of one run produce equal results, equal documents and equal streams.

**Cost — the big one.** *Nothing supplies a Retail executor.* The scheduler can
execute; it has nothing to execute. Writing one means knowing both Retail's
generators and the platform's contracts, and neither layer may import the
other: a domain may not depend on the platform (PADR-002), and the platform may
not depend on a domain. The natural home is the **CLI layer**, which already
imports both, or a small `eds/runners/` package chartered to do exactly this.
That is a wiring phase and it is where the platform stops being a claim.

**Cost.** Multi-tick resumption is coarse (challenge 1 above).

**Limitation.** A multi-tick run re-executes the whole plan on every tick. For
Retail that regenerates everything each time, so today's sensible run is a
single tick. The scheduler cannot know that — what a tick means to a domain is
the executor's business — but a caller should.

**Limitation.** No cancellation. `CANCELLED` is recorded for stages a stop or a
failure passed over; there is no way to interrupt a run from outside. An
explicit non-goal.

## Future integration

**Parallel execution.** `ExecutionPlan.levels()` already groups stages that
have no dependency between them. Making one level concurrent means changing
`_one_pass` and nothing else: ordering, persistence, events and results are all
unaffected, because the plan decides ordering, the project decides persistence,
and events order by an assigned sequence rather than by arrival. The one thing
that would need care is sequence assignment, which must stay deterministic —
assign numbers in the level's declared order, not in completion order.

**Growth engine (P007).** Runs between ticks: read `RunResult.rows_by_dataset`
and `state.last_identifiers`, decide how much the enterprise grew, write the
new identifiers back. It needs a hook the scheduler does not currently have,
and adding one is a scheduler change rather than a contract change.

**Snapshots.** Run after a successful tick, reading the same state the
scheduler just wrote.

**Change capture.** Reads the event stream in sequence, treating
`StageCompleted` as a change boundary — which is why a dry run must not emit
one.

## What this decision does not permit

The scheduler must not learn what a stage means. A test forbids it importing
`polars`, `eds.domains`, `eds.adapters`, `threading`, `asyncio` or `logging`,
and forbids any wall-clock call. If it begins needing to know what a domain
does, the need belongs in an executor. If it begins needing to know what a
result means, the need belongs in a contract.
