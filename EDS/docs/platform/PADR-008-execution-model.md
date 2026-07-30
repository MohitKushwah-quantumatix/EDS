# PADR-008: The Execution Model Plans, It Does Not Execute

**Status:** Accepted (P002)

**Builds on:** PADR-006, which established that a domain *describes* its stages
rather than running them.

## Context

PADR-006 gave every domain a description: ordered stages, each declaring the
datasets it reads and writes. It also said that description was "exactly the
dependency graph a scheduler consumes".

P002 tests that claim. If the description is not enough to derive a correct,
deterministic execution order, then PADR-006 was wrong and the protocol needs
execution back. If it is enough, the platform gains a planning layer and the
scheduler that comes later has something to schedule.

## Decision

A new package, `eds/platform/execution/`, answers **"what should run?"** and
nothing else. It reads stage declarations, derives a dependency graph,
validates it, and produces an immutable `ExecutionPlan`.

It does not execute generators, write datasets, read Parquet, touch an adapter,
or create state. A test enforces this rather than trusting it: the package may
not import `polars`, `eds.domains`, `eds.adapters` or even `eds.core`. A plan
that could hold a callable or a frame would be one refactor away from becoming
an executor.

### Edges are derived, not declared

The central decision. A stage does not name the stages it follows; it names the
datasets it reads and writes. Stage `B` depends on `A` exactly when
`B.requires` intersects `A.produces`.

Declared stage-to-stage edges would restate something the data flow already
says, and two statements of one fact drift. Deriving them means a stage that
starts reading a new dataset gains an edge automatically, and one that stops
producing a dataset loses its dependants automatically.

The consequence worth stating: **the order a domain lists its stages in carries
no authority.** It is used only to break ties.

### Ties break on declaration order

A topological sort is not unique whenever two stages are independent, and a
planner that returns an arbitrary one of several valid orders is not
deterministic. Kahn's algorithm with a tie-break fixes that; the question is
which tie-break.

Declaration index was chosen over alphabetical. Alphabetical is canonical —
the plan becomes a pure function of the graph, independent of how the domain
listed things — but it is also arbitrary, and it would surprise: a domain
listing `extract, transform, load` would be planned `extract, load, transform`
if those three were independent. Declaration order is the one preference signal
the author actually gave, and it is equally deterministic.

### Validation fails, it does not warn

`build_execution_plan` raises `PlanValidationError` carrying every issue found.
There is no "plan with warnings", because a plan is a thing somebody will
eventually execute and a partially valid one invites exactly that.

Checked: empty graph, duplicate stage name, dataset produced by two stages,
requirement nothing produces, dependency cycle, unknown plan target.

`duplicate_producer` was not on the original list but belongs: two stages
writing one dataset is a race however it is executed, and it makes the edges
ambiguous because a consumer would depend on both.

### Plans can be narrowed

`build_execution_plan(domain, targets=["customers"])` plans those stages and
their transitive dependencies, and nothing else — `make customers` rather than
`make all`. This is what gives "missing stage" a meaning distinct from "unknown
dependency", and a scheduler resuming a partial run needs it.

### Levels are computed, parallelism is not decided

Each stage carries a `level`: one more than the deepest stage it depends on.
Stages sharing a level have no dependency between them and *could* run
concurrently. The planner computes this and stops. Whether to actually
parallelise is the scheduler's decision and depends on cost, resources and
isolation — none of which the planner knows.

For Retail this yields four levels of one stage each, because each command
genuinely depends on the previous one. The model reports the truth rather than
inventing parallelism.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| **Declared `depends_on: tuple[str, ...]` on each stage** | Simpler graph construction, but restates the data flow and can disagree with it. The failure mode — an edge that says one thing and the datasets another — is silent. |
| **Plan at dataset granularity** (39 nodes, not 4) | More latent parallelism, and arguably more honest. But it does not correspond to anything executable: the CLI's unit of work is a command, not a dataset. Reconsider when something can execute a single dataset. |
| **Return a plan plus issues instead of raising** | Matches the repository's data-validation style, but data validation reports on data that already exists. A plan does not have to exist if it is wrong. |
| **`ExecutionPlanner` / `ExecutionValidator` classes** | Both would be stateless — namespaces with extra steps, and the only validator in the repository shaped that way. Functions match `validate_order_data` / `assert_valid_order_data`. If planning acquires policy, that policy is what would justify an object. |
| **Alphabetical tie-break** | Canonical, but arbitrary and surprising. See above. |

## Consequences

**Good.** PADR-006's claim is now demonstrated rather than asserted: the
planner derives Retail's execution order from data flow alone, knowing nothing
about the CLI, and gets `master-data → customers → journey → commerce`. A test
asserts that agreement, which closes the risk that the description and the CLI
drift apart.

**Good.** The plan is inert data — names, positions, levels — so it can be
compared between runs, logged, cached, or handed to a component that does not
exist yet.

**Cost.** Nothing consumes a plan today. That is deliberate: the CLI cannot use
it without changing CLI behaviour, which is out of scope, and building an
executor now would repeat the P001 mistake of designing an interface before its
caller exists. The planner is exercised by the real domain and 62 tests, which
is what keeps it from being a speculative abstraction.

**Limitation.** Stage granularity is CLI-command granularity, so intra-command
structure is invisible. Retail's `commerce` stage is really seven features
(F004–F010) with genuine dependencies between them, and the planner sees one
node. Splitting it would give the scheduler more to work with, but it would
also break the one-stage-per-command correspondence the CLI relies on. Revisit
only if a scheduler can execute below command level.

**Limitation.** A requirement nothing produces is always an error, so a domain
cannot yet declare that it consumes externally supplied data. No domain needs
that today; it would be an explicit `external_inputs` declaration on the domain
when one does.

## Future integration

**Scheduler.** Consumes `ExecutionPlan.levels()` for what may overlap and
`PlannedStage.depends_on` for what must not. Adds execution, retries and
failure policy. The plan stays inert; the scheduler holds the mutable run.

**State.** `PlannedStage.produces` is what a state store would key on to answer
"is this already built, and is it stale?". Combined with `targets`, that gives
incremental runs: plan only what is missing or out of date. The planner needs
no change for this — the caller narrows the targets.

**Clock.** Orthogonal. The plan says what runs and in what order; the clock says
*when*, and for which simulated date. A daily simulation is the same plan
executed once per tick, which is why the plan must stay free of state.

## What this decision does not permit

The execution package must not gain the ability to run anything. If a future
change needs a plan to carry a callable, that is a signal to build a separate
executor that maps stage identifiers to callables — keeping the plan itself
inert and comparable.
