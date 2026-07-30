# Platform Roadmap

## Delivered — P001, Platform Foundation

| Layer | State |
| --- | --- |
| `eds/core/` | Complete for today's needs: schema, frames, random streams, validation framework, config loading |
| `eds/platform/` | Project, metadata, domain registry. Clock and state were declared placeholders; the clock became `eds/platform/time/` in P004 |
| `eds/domains/retail/` | The whole Retail simulator, unchanged in behaviour |
| `eds/adapters/` | Protocols plus the Parquet adapter |
| `eds/cli/` | Untouched. Four commands, identical behaviour |

Retail's business logic did not change. Output is byte-identical. All 1,700
pre-existing tests pass unmodified, and 45 architecture tests were added.

## Delivered — P002, Execution Model

`eds/platform/execution/` turns a registered domain's stage declarations into a
validated, ordered, immutable `ExecutionPlan`. It plans; it does not execute
(PADR-008). Nothing consumes a plan yet — the scheduler is its first caller.

## Delivered — P003, Project and State Foundation

`eds/platform/project/` gives a simulated enterprise a durable identity
(`ProjectManifest`), somewhere to record progress (`SimulationState`), a
workspace layout, and a storage-independent document store. It stores; it does
not run (PADR-009). Nothing consumes a project yet — the scheduler is its first
caller.

## Delivered — P004, Simulation Time Model

`eds/platform/time/` defines what time means: a period, a tick, a calendar and
a clock, all immutable values. Advancing produces a new clock; nothing reads
the wall clock, sleeps or schedules (PADR-010). It supersedes P001's
`clock.py` placeholder. Nothing consumes a clock yet — the scheduler is its
first caller, and it is now the third interface waiting for that one component.

## Delivered — P005, Simulation Run Model

`eds/platform/run/` binds a project, a plan and a clock into one immutable,
validated configuration. It is the only module allowed to depend on all three,
and the reason the scheduler will take one argument rather than six
(PADR-011). It validates; it does not execute.

## Delivered — P005.1, Runtime Contracts

`eds/platform/runtime/` defines the vocabulary execution is reported in:
results, events, failures, warnings, progress and a status model with declared
transitions. Every one is a frozen fact and none carries wall-clock time, so
two runs of one simulation produce equal results (PADR-012). It describes; it
contains no behaviour.

## Delivered — P006, Runtime Scheduler

`eds/platform/scheduler/` is the first executable component: it takes one
`SimulationRun`, calls the platform's five declared modules in order, and
returns P005.1's contracts unchanged. It required no change to any of them.
It cannot execute a domain — a `StageExecutor` is supplied by the caller
(PADR-013), which is what keeps it free of business and testable with a fake.

## Delivered — P006.1, Retail Runtime Integration

`eds/runners/retail/` wires Retail into the platform. A complete simulation now
runs through `SimulationRun → Scheduler → RetailExecutor → domain → adapters →
project → contracts`, producing output **byte-identical to the CLI's**, with no
platform module knowing Retail exists. It needed no change to any frozen module
(PADR-014).

## Delivered — Retail Temporal Evolution

`eds/domains/retail/temporal/` makes Retail a simulation rather than a snapshot.
The execution date is now the reference date, each of the thirty-nine datasets
declares what a passing day does to it, and a stage founds its datasets if they
are empty and continues them if they are not — so **a year of trading is a year
of business**: 365 consecutive days, each adding to the last, with no rewritten
row, no repeated identifier and no broken temporal rule (ADR-013, ADR-014).

A day is seeded by its date rather than its position, which makes the strongest
property here testable in bytes: nine days run at once and nine days run as four
then three then two produce the same enterprise. Determinism survives being
interrupted, divided and continued.

The founding day is unchanged, so `eds generate` and the byte-identical
guarantee are unchanged. No platform module, scheduler, runtime contract or
adapter was touched.

## Extension points now available

| Point | Where | What it enables |
| --- | --- | --- |
| `SimulationDomain` + registry | `eds.platform.domain` | A second business domain |
| `DatasetWriter` / `DatasetReader` | `eds.adapters.base` | A second output target |
| `PLATFORM_CONTRACT_VERSION` | `eds.platform.metadata` | Versioning the domain and adapter contracts |
| `read_yaml_mapping` / `build_model` | `eds.core.config` | A domain's own configuration, loaded the same way |
| `SimulationClock` / `Tick` | `eds.platform.time` | What a scheduler advances between runs |
| `Calendar` protocol | `eds.platform.time` | A region's or industry's own working week |
| `SimulationRun` | `eds.platform.run` | The scheduler's single input |
| `RunConfiguration` | `eds.platform.run` | CLI flags and YAML run files, round-tripped |
| `RunResult` / `StageResult` | `eds.platform.runtime` | The scheduler's single output |
| `ExecutionEvent` | `eds.platform.runtime` | What change capture reads, in sequence |
| `StageExecutor` | `eds.platform.scheduler` | How a domain is actually run |
| `eds/runners/<domain>/` | `eds.runners` | A domain wired into the platform |
| `BusinessContext` | `eds.domains.retail.temporal` | The whole of what a domain needs of time |
| `Temporality` + `DATASET_TEMPORALITY` | `eds.domains.retail.temporal` | What a passing day does to a dataset |
| `advance_day` | `eds.domains.retail.temporal` | Running Retail for one business date |
| `ExecutionPlan` / `PlannedStage` | `eds.platform.execution` | What a scheduler schedules |
| `plan_domain(name, targets=...)` | `eds.platform.execution` | Narrowed plans, for incremental runs |
| `Project` / `ProjectManifest` | `eds.platform.project` | A resumable simulated enterprise |
| `SimulationState` | `eds.platform.project` | Where the clock and scheduler record progress |
| `StateStore` protocol | `eds.platform.project` | Documents in a database or object store |

## Not started — and deliberately so

Each was explicitly out of scope for P001, and each has a home reserved.

**Simulation lifecycle** — growth engine, snapshots. Home: `eds/platform/`.
The binding constraint is PADR-004: whatever arrives must keep a run a pure
function of `(project, seed, upstream data)`. The scheduler arrived in P006 and
kept it.

**A second domain.** Healthcare means `eds/domains/healthcare/` plus
`eds/runners/healthcare/`, and nothing else. P006.1 proved the shape with
Retail; the claim is fully tested when a second domain needs no platform
change.

**Change tracking** — SCD and CDC. Both inputs now exist: the notion of
"slowly" that a slowly changing dimension needs is a tick, and the change
boundary a capture reader needs is a `StageCompleted` event.

**Further adapters** — SQL Server, PostgreSQL, MongoDB, Kafka. Each is a new
package under `eds/adapters/` implementing the two protocols. Expect the
protocols to need widening for the first adapter that is not file-shaped;
that is a cheap change while there is one implementation.

**Further domains** — Healthcare, Banking, Manufacturing. Each is a new
package under `eds/domains/`. The platform claim is that none of them requires
a platform change; the first one to be attempted is the real test of that
claim, and it should be treated as such.

**Operational surface** — REST API, Docker, Kubernetes.

## Retiring the compatibility shims

The roughly hundred shim modules under `eds/domain/`, `eds/generators/`,
`eds/validation/`, `eds/exporters/` and `eds/config.py` are a deprecation
layer, not a permanent fixture. A sensible sequence, none of it urgent:

1. **Now.** Shims in place, tests untouched. Both paths work.
2. **Next phase.** Move the test suite onto the new paths, one test module at
   a time. Each move is independently verifiable — the compatibility test
   already proves the objects are identical, so a move cannot change meaning.
3. **After that.** Add a `DeprecationWarning` on shim import, once nothing
   inside the repository triggers it.
4. **A major version.** Delete the shims.

Nothing forces step 2 to happen soon. The shims cost lint and type-check time
and some visual noise, and they buy the guarantee that no external consumer
was broken by P001.

## Questions closed since P001

1. **Should Retail register itself through `SimulationDomain`?** *Closed in
   P001.1.* It does. Attempting a real implementation is what exposed that
   `generate()` could not be implemented honestly, which produced PADR-006.
2. **Is `SimulationConfig` in the right place?** *Closed in P001.1 by
   PADR-007.* It stays in the domain — it aggregates thirteen retail models.
   The type that was misplaced was `PlatformConfig`, which moved Core →
   Platform.
3. **Does the adapter protocol survive a non-file target?** *Partly closed in
   P001.1 by the PADR-003 revision.* The destination is now bound at
   construction rather than passed per call, and `WriteResult` replaced
   `tuple[Path, ...]`. Whether that is sufficient is still unproven — see
   below.
4. **Should `Project` absorb `PlatformConfig`?** *Closed in P003 by PADR-009.*
   They no longer overlap: `PlatformConfig` is run configuration and
   `ProjectManifest` is durable identity.
5. **Was `SimulationState` drawn correctly?** *Closed in P004.* The clock
   arrived and P003 needed no change to accept it — `current_date` was the
   right field, stored in the right place, at the right granularity.

## Open questions for architecture review

1. **Does the revised adapter contract survive a real non-file adapter?** The
   `Path` is gone from the protocol, but the contract has still only ever been
   implemented by a file writer. The first SQL or Kafka adapter is the real
   test. Expect transactions, batching or partitioning to need expressing.

2. **Is stage granularity right?** The planner sees Retail as four nodes
   because that is what the CLI executes. `commerce` is really seven features
   with genuine dependencies between them, invisible to the planner. Splitting
   it would give a scheduler more to work with and break the
   one-stage-per-command correspondence. Only worth revisiting if something can
   execute below command level.

3. **How does a domain declare externally supplied inputs?** Today a
   requirement nothing produces is always an error, so every domain must be
   closed. A domain reading third-party reference data would need an explicit
   `external_inputs` declaration. No domain needs it yet.

4. **When does the CLI learn about workspaces?** Today it writes to
   `PlatformConfig.output_directory` and knows nothing about projects. Pointing
   it at `workspace.data_directory` would change CLI behaviour, so it waits for
   a phase chartered to do that.

5. **Does `Workspace` need a location abstraction?** It is filesystem-shaped
   because adapters write datasets by location. A workspace on object storage
   would need more. The document store is already storage-independent, so this
   is a narrower question than it looks.

6. **Where is a run's time configuration persisted?** *Still open after P005,
   deliberately.* A project stores the simulated *date*; it does not store
   which period, tick or calendar produced it, so a resumed run could in
   principle be given a different tick. `RunConfiguration` could have carried
   them, but only by duplicating what the clock already holds. The likely
   answer is that a project records its last run's configuration, which is a
   P003-shaped change and belongs with whichever phase owns run configuration
   end to end.

7. **Do the platform primitives compose?** *Closed in P006.* They do. The
   scheduler executes whole runs — multi-tick, resumed, failed, targeted,
   rehearsed — and required no change to any of P002 through P005.1.

8. **Does `Progress` have a producer?** *Closed in P006* — the scheduler
   builds one. One wording question survives: PADR-012 describes
   `completed_stages` as stages that "reached a terminal status", which every
   stage in a finished result has. The scheduler reports successful-or-skipped
   stages, the only reading that makes a proportion mean anything.

10. **Can `completed_stages` express a multi-tick resume?** *Raised by P006.*
    P003 records which stages have ever completed and refuses a duplicate, so
    a run interrupted on tick 40 resumes correctly in date but coarsely in
    stages. Right for every single-tick run that exists today; wrong for a
    long one. The fix is a P003 change and should wait for something that
    needs it (PADR-013).

11. **When does Retail become time-aware?** *Closed by Retail Temporal
    Evolution.* The execution date is the reference date, and a day adds to a
    history rather than replacing it. `reference_date` survives as the default
    for a caller with no date — which is what `eds generate` is — so the CLI is
    untouched (ADR-013).

12. **When does the CLI become a caller of the runner?** Retail now has two
    execution paths, proven equivalent by a test that compares all thirty-nine
    files byte for byte. The duplication should end with the CLI calling
    `eds/runners/retail/`, and that test is what will make the change safe
    (PADR-014).

13. **Is `commerce` too coarse to resume?** *Sharpened by P006.1.* Seven
    features run in one stage, so a failure in reviews discards the whole
    stage's work and payments cannot run without regenerating orders.
    Splitting it is a Retail change — its registry declares the stages — and
    the platform can already plan seven nodes.

14. **Can a project be carried forward by a second run?** *Raised by Retail
    Temporal Evolution.* `SimulationRun` refuses any run whose clock does not
    stand exactly where the project last stopped, and the scheduler leaves the
    clock on the final tick rather than past it — so there is no date a second
    run can legally start on. Re-running the last date would trade that day
    twice; starting on the next one is refused. Retail itself needs nothing:
    its history is on disk and a day is seeded by its date, so continuation is
    a matter of pointing a run at a later date. What is missing is a platform
    notion of "continue", distinct from "resume". Closing question 10 in the
    same change would be natural, since both are about a run's position rather
    than its stages.

15. **Should a day's commerce settle on the day it falls?** *Raised by Retail
    Temporal Evolution.* A day's orders currently resolve their whole
    downstream chain immediately, so a parcel arriving next week and a review
    written next month are generated today. Relationally everything is in
    order; but the datasets hold rows dated after the business date, so
    "the enterprise as at today" would show the future. The fix needs question
    13 answered first — settlement can only be deferred to a later day if it
    can be executed below command level.

9. **Where does run history live?** A `RunResult` round-trips completely, so a
   project could store its runs as documents through P003's `StateStore` with
   no new machinery. Whether it should — and whether that is what closes
   question 6 — is a decision for whichever phase owns run history.
