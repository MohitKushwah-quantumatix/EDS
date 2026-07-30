# PADR-011: The Run Binds the Primitives So the Scheduler Takes One Argument

**Status:** Accepted (P005)

**Builds on:** PADR-008 (plans are inert), PADR-009 (the project stores, it does
not run), PADR-010 (time is a value).

## Context

The platform has three primitives, each built without a consumer and each
provably independent of the other two. A test in P004 asserts that no plan
imports a project, no project imports a clock, and so on. That independence is
what makes them reusable.

It is also what leaves a gap. Each is valid on its own; none can check that it
*agrees* with the others. That the plan is for the project's domain, that the
clock sits where the project's state says it does, that a named target is a
stage that exists — these are cross-object facts, and cross-object facts need
somewhere to live. Without that place, a scheduler's signature becomes six
parameters of which several must be consistent and none can say so, and the
consistency check gets written inside the scheduler, where it is entangled with
execution and cannot be tested without running anything.

## Decision

Five concepts. Everything is a frozen value.

| Concept | Owns | Serialisable |
| --- | --- | --- |
| `RunMode` | Which stages: full, targeted, resume | Yes |
| `StopCondition` | When to stop: `EndOfPeriod`, `AfterTicks`, `AfterStage` | Yes |
| `RunConfiguration` | What was asked for, independent of what it was asked of | **Fully, both ways** |
| `SimulationRun` | Project + plan + clock + configuration, checked against each other | One-way summary only |
| `RunIssue` / `RunValidationError` | What disagrees with what | — |

### A run validates; it does not execute

`SimulationRun` holds no callable, opens nothing, writes nothing and advances
nothing. `validate()` returns every issue; `assert_valid()` raises. `create_run`
validates before returning, so **holding a run from the factory is a guarantee
that its parts agree** — the same guarantee `ExecutionPlan` gives about its
graph (PADR-008).

Constructing `SimulationRun` directly deliberately does *not* validate. A caller
diagnosing a broken run has to be able to hold one and ask it what is wrong.

### The scheduler takes one argument

That is the point of the type, and the success criterion the brief names. Not
`run(project, plan, clock, targets, mode, stop)`, which invites a caller to pass
five consistent things and one that is not.

### Dry run is not a mode — the challenge

The brief listed "dry run (planning only)" beside full, targeted and resume.
Implemented as specified it would be a fourth enum member. It is not, and this
is the one place P005 deviates from the specification.

**1. Current design (as specified).** `RunMode ∈ {FULL, TARGETED, RESUME, DRY_RUN}`.

**2. Proposed design.** `RunMode ∈ {FULL, TARGETED, RESUME}` answers *which
stages*; `RunConfiguration.dry_run: bool` answers *whether anything is written*.

**3. Advantages.** The two questions are independent, and treating them as one
makes combinations inexpressible. "What would resuming actually do?" is an
obviously useful question and a four-member enum cannot ask it. Twelve
combinations become expressible instead of four, all four concepts are still
represented, and neither field can contradict the other.

**4. Disadvantages.** A boolean beside an enum is a shape worth being suspicious
of — it often signals a mode that was not thought through. It also means a
caller must set two fields rather than one, and a scheduler must check two.
Against that: the fields are genuinely orthogonal, which is exactly the case
where a flag is right rather than lazy.

**5. Migration impact.** None. P005 is new, nothing consumes it, and the
specification's four concepts are all still expressible.

**6. Recommendation.** Adopt the proposed design. Reverting is a one-line enum
change plus a field removal if the review disagrees.

### Two types, because half of a run can be written down

`RunConfiguration` is entirely primitives and closed values, so it round-trips
through a document, fits in a YAML file, and maps onto a future set of CLI
flags. `SimulationRun` cannot: a project handle holds a live store, and a clock
holds a calendar, which is code.

That asymmetry is why they are separate types rather than one object with a
serialisable subset. A half-serialisable type invites somebody to persist it
anyway. `SimulationRun.to_document()` exists but is explicitly **one-way** — an
audit record and a log line, not a means of reconstruction — and there is no
`from_document`, which a test asserts, because its absence is the design.

### Stop conditions are a closed set

The opposite choice from `Calendar` (PADR-010), for the opposite reason. A
calendar is *asked* a question and answers it itself, so anybody may write one.
A stop condition is *read* by a scheduler that must interpret every kind that
exists, so an open protocol would let a caller construct one no scheduler can
honour. Declaring the set here means adding a criterion is a considered platform
change, and a scheduler can match exhaustively.

### The run does not restate the tick policy

The brief lists "tick policy" among a run's optional parts. P004 established
that a tick's meaning comes from its unit and its calendar, and the clock holds
both. Declaring either on the run as well would create two records of one fact
that could disagree. For the same reason, the run holds no time range: it holds
a clock, and the clock holds the period.

### What validation actually checks

Cross-object rules, which is everything a single primitive cannot see:

| Rule | Catches |
| --- | --- |
| `domain_mismatch` | A plan built for a different domain than the project simulates |
| `empty_plan` | A run that would do nothing |
| `unknown_target` | A named stage that is not in the plan |
| `clock_state_mismatch` | A clock built for a different period than the project reached |
| `nothing_to_resume` | A resume where every stage is already recorded complete |
| `unreachable_stop_condition` | `EndOfPeriod` against an open-ended clock |
| `unknown_stop_stage` | `AfterStage` naming a stage outside the plan |
| `unreadable_state` | A corrupt state document, reported rather than raised mid-validation |

Plus every `ProjectIssue` the project reports about itself, forwarded rather
than restated, so those rules stay in one place.

Single-object rules stay where they belong: a tick count of zero and a targeted
run with no targets are `ValueError`s raised where the field is set.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| **No run type; scheduler takes six arguments** | The consistency check ends up inside the scheduler, entangled with execution and untestable without running something. The gap is real; the only question is where it is filled. |
| **One type — merge `RunConfiguration` into `SimulationRun`** | Half of it would be serialisable and half not, which invites somebody to persist a project handle. |
| **`RunTarget` as its own type** | A target is a stage name. Wrapping a string in a class adds a name without a distinction, and the plan already owns what a stage is. |
| **`RunValidator` as a class** | A class with no state is a namespace with extra steps — the same reasoning that made the planner functions (PADR-008). The rules belong on the object that holds what they compare. |
| **Run mutable, carrying execution progress** | That is a *run record*, not a run configuration, and it belongs to the scheduler. Progress already has a home in `SimulationState`. |
| **Run resolves and caches state at construction** | State changes as a run proceeds; a cached copy goes stale the moment it is used. `read_state()` reads every time. |
| **Open `StopCondition` protocol** | A caller could construct a criterion no scheduler knows how to honour. |
| **Multiple stop conditions, first to fire** | Realistic but speculative. One condition covers every case anybody has stated; `AnyOf` is a compatible addition when something needs it. |
| **Run derives its own clock** | Would require the run to own a period and a tick, duplicating the clock and reopening P004's two-sources-of-truth problem. |
| **`create_run` returns issues instead of raising** | `validate()` already does that. A factory that returns something possibly-invalid gives up the guarantee that makes one argument safe. |

## Consequences

**Good.** The scheduler's signature is settled, and settled before the scheduler
exists — which is the whole reason to build one of these before the other. Every
cross-object rule is testable without executing anything: the 91 tests in
`test_platform_run.py` run in about a second.

**Good.** The three primitives stayed independent. P005 required no change to
P002, P003 or P004, and a test asserts none of them imports the run package. The
dependency is strictly one-way, which is what keeps them reusable on their own.

**Good.** `clock_state_mismatch` is a rule nothing else could have. The clock is
valid, the state is valid, and only a run sees both. It catches resuming with a
clock built for the wrong period, which is otherwise a silent wrong answer
rather than a failure.

**Cost.** A fourth platform interface with no consumer. P002, P003, P004 and now
P005 have all been built without one, and the scheduler is the first thing that
will hold them together. P005 narrows the risk rather than adding to it — the
composition it was uncertain about is now expressed and tested — but it does not
eliminate it.

**Cost.** `run_id` is identity nothing needs today. Without it, two runs of one
project are indistinguishable in a log and a scheduler recording per-run
progress would have to mint an identifier the platform declined to define. It
also means two otherwise-identical runs are unequal; compare `configuration`
when the question is "the same configuration".

**Limitation.** Validation reads the project's state, so it touches storage.
That is not free and it is not pure, but the alternative is a check that cannot
see what a project has done. A corrupt state document is reported as
`unreadable_state` rather than raised, so validation still explains a broken run
instead of failing while trying to.

**Limitation.** `remaining_stages()` reports what state says regardless of mode.
Whether to honour it is a scheduler's judgement — a full run may legitimately
redo completed work — so the run describes and does not decide.

## Future integration

**Scheduler (P006).** `def execute(run: SimulationRun) -> RunResult`. It reads
`run.plan.levels()` for what may overlap, `run.remaining_stages()` for what is
outstanding, `run.mode` for whether to honour that, `run.clock` for the date to
generate against, `run.stop_condition` for when to stop, and `run.is_dry_run`
for whether to write. After each stage it writes state through
`run.project.write_state`, and it advances by rebinding `run.clock.advance()` —
the run itself never changes, because the run is the configuration and the
scheduler holds the progress.

**Growth engine.** Reads `run.clock.ticks_elapsed` and
`run.project.read_state().last_identifiers`. It needs nothing from the run that
is not already there.

**CLI.** `RunConfiguration` maps one-to-one onto flags — `--mode`, `--target`,
`--stop-after-ticks`, `--dry-run` — and `from_document` gives the same shape
from a YAML file. That is the phase in which the CLI would learn about
workspaces, which the roadmap has open.

**Where a run's time configuration is persisted.** Still open, and deliberately
not closed here. `RunConfiguration` could have carried a period and a tick, but
only by duplicating the clock. The right answer is probably that a project
records the configuration of its last run — including the clock's period, tick
and calendar — which is a P003-shaped change and belongs with whichever phase
owns run configuration end to end.

## What this decision does not permit

The run model must not gain the ability to execute. A test forbids it importing
`polars`, `eds.domains`, `eds.adapters`, `threading` or `asyncio`, and forbids
any call to `now()`, `today()` or `sleep()`. It may depend on all three
primitives — it is the only module that may — but nothing may depend on it
except a scheduler, and no domain may import it at all.
