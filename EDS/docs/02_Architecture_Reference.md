# Enterprise Data Simulator — Architecture Reference Manual

**EDS v1.0 · Official documentation · Document 2 of 5**

Audience: architects and senior engineers. Reference only — no tutorials.

Companion documents: [Handbook](01_Handbook.md) ·
[Maintainer Guide](03_Maintainer_Guide.md) ·
[Package Reference](04_Package_Reference.md) ·
[Developer Quick Start](05_Developer_Quick_Start.md) ·
[Documentation index](README.md)

Terminology is defined once, in the [Handbook glossary](01_Handbook.md#19-glossary),
and used unchanged here.

---

## Table of contents

1. [Architecture overview](#1-architecture-overview)
2. [Architecture principles](#2-architecture-principles)
3. [Major components](#3-major-components)
4. [Component responsibilities](#4-component-responsibilities)
5. [Package relationships](#5-package-relationships)
6. [Data flow](#6-data-flow)
7. [Simulation lifecycle](#7-simulation-lifecycle)
8. [Store of Record](#8-store-of-record)
9. [Configuration model](#9-configuration-model)
10. [Platform architecture decision records](#10-platform-architecture-decision-records)
11. [Domain architecture decision records](#11-domain-architecture-decision-records)
12. [Architecture diagrams](#12-architecture-diagrams)
13. [Dependency diagrams](#13-dependency-diagrams)
14. [Glossary](#14-glossary)

---

## 1. Architecture overview

EDS is a platform for simulating a business, with Retail as its first and only
implemented domain.

The architecture answers one question: **how can the machinery of simulation be
reused for any business without knowing anything about any business?** Every
decision below follows from that, and the test of success is precise — a
Healthcare, Banking or Manufacturing domain must be addable without editing a
single line of platform code.

Five layers, one strict dependency direction:

| Layer | Package | Owns |
| --- | --- | --- |
| **Core** | `eds.core` | The shared vocabulary: dataset declarations, deterministic random streams, frame construction, validation framework, YAML loading |
| **Platform** | `eds.platform` | What it means to *run* a simulation: identity, planning, time, runs, contracts, scheduling |
| **Domains** | `eds.domains` | The businesses being simulated: entities, generators, rules, temporal evolution |
| **Adapters** | `eds.adapters` | Where data is persisted and read back — the Store of Record |
| **Runners** | `eds.runners` | The integration boundary. The only package that may import both a domain and the platform |

Two prohibitions carry most of the weight:

* **The platform may not import a domain** (PADR-002).
* **A domain may not import the platform's runtime** (PADR-002, PADR-016).

Since neither side may name the other, a third party must translate. That party
is `eds.runners`, and PADR-015 makes it a permanent boundary rather than an
implementation convenience.

---

## 2. Architecture principles

| Principle | Consequence | Record |
| --- | --- | --- |
| The platform generalises mechanics, never meaning | No generic "entity" or "transaction" abstraction exists | PADR-001 |
| Domains are platform-independent | A domain is usable without a scheduler | PADR-002 |
| Adapters are isolated | No generator imports an adapter; they meet at `DataFrame` | PADR-003 |
| The platform owns lifecycle | Seed, timezone, locale and output location are platform settings | PADR-004 |
| Pre-platform import paths keep working | `eds.config`, `eds.generators.*` still resolve | PADR-005 |
| Descriptions do not execute | The domain protocol and the execution plan describe only | PADR-006, PADR-008 |
| Configuration is owned by whoever it constrains | Platform settings and domain settings are separate models | PADR-007 |
| Simulated time is a value | Advancing produces a new clock; nothing mutates | PADR-010 |
| The scheduler takes one argument | A run binds project, plan and clock before execution | PADR-011 |
| Contracts are facts, not behaviour | Results and events carry no logic | PADR-012 |
| The scheduler coordinates only | It cannot execute a domain; the executor is an argument | PADR-013 |
| The runner is the integration boundary | The only package with both vocabularies in scope | PADR-014, PADR-015 |
| Data is domain state | A domain keeps no execution state; absence of data means founding | PADR-016 |
| No abstraction before duplication | Registries, base classes and protocols appear on evidence | throughout |
| Determinism is a tested property | Byte-identical output is asserted, not assumed | ADR-005, PADR-005 |

---

## 3. Major components

```
eds.core
├── schema.py            Dataset, ForeignKey — the declaration everything reads
├── frames.py            Schema-conformant frame construction, business codes
├── random_streams.py    Named, reproducible random streams from one seed
├── config.py            YAML loading, ConfigError, model building
└── validation/          Schema, key and foreign-key checking

eds.platform
├── metadata.py          Platform name and contract version
├── domain.py            SimulationDomain protocol, DomainStage, the registry
├── config.py            PlatformConfig — seed, timezone, locale, output
├── execution/           DependencyGraph, PlannedStage, ExecutionPlan, plan_domain
├── project/             Project, ProjectManifest, SimulationState, StateStore, Workspace
├── time/                SimulationDate, Tick, Calendar, TimeRange, SimulationClock
├── run/                 SimulationRun, RunConfiguration, RunMode, StopCondition
├── runtime/             ExecutionStatus, Failure, StageResult, RunResult, ExecutionEvent, Progress
└── scheduler/           StageExecutor protocol, StageRequest/Output, execute()

eds.domains.retail
├── registry.py          RetailDomain — the concrete SimulationDomain
├── config.py            Every Retail settings model and loader
├── domain/              Entity schemas and enums
├── generators/          Business event generators, F001–F010
├── temporal/            BusinessContext, temporality, identity, merge, evolution
└── validation/          Retail business rules

eds.adapters
├── base.py              DatasetWriter, DatasetReader, WriteResult, AdapterError
└── parquet/             Reader, writer, ParquetAdapter

eds.runners.retail
├── executor.py          RetailExecutor — the StageExecutor the scheduler runs
└── stages.py            Runs a stage for a date; classifies failures
```

`eds.cli` is a thin Typer application over the Retail generators. It predates the
platform and does not route through it — see PADR-005.

---

## 4. Component responsibilities

| Component | Owns | Never owns |
| --- | --- | --- |
| `eds.core` | Declarations, determinism primitives, validation machinery, config loading | Any business meaning; any storage format |
| `eds.platform.domain` | The protocol a domain satisfies; the registry it announces itself to | Executing a domain |
| `eds.platform.execution` | Deriving an ordered plan from a domain's declarations | Running anything |
| `eds.platform.project` | Durable identity, workspace layout, recorded state, document persistence | Deciding what to record |
| `eds.platform.time` | Period, tick, calendar, clock; what advancing means | Deciding when to advance |
| `eds.platform.run` | Binding project + plan + clock; validating that they agree | Executing |
| `eds.platform.runtime` | The vocabulary an execution is reported in | Any behaviour |
| `eds.platform.scheduler` | Ordering stages, advancing the clock, persisting progress, emitting events, assembling the report | Running a stage; knowing a business |
| `eds.domains.retail` | What the data is, how it is generated, what makes it valid, what a day does to it | Destinations, clocks, runs, projects, schedulers |
| `eds.adapters` | Reading and writing datasets — the Store of Record | Business meaning |
| `eds.runners.retail` | Translating a request into a business context; reading upstream and history; invoking the domain; writing; classifying failures | Business rules, orchestration, persistence policy, scheduling, planning |

---

## 5. Package relationships

```
                    eds.core
                        ▲
        ┌───────────────┼───────────────┬──────────────┐
        │               │               │              │
   eds.platform    eds.domains    eds.adapters    (eds.cli)
        ▲               ▲               ▲
        └───────────────┴───────────────┘
                        │
                   eds.runners        ← imports all three
```

| Package | May import | Must not import |
| --- | --- | --- |
| `eds.core` | `eds.version` only | Everything else in `eds` |
| `eds.platform` | `eds.core` | `eds.domains`, `eds.adapters`, `eds.runners` |
| `eds.domains` | `eds.core`, `eds.platform.domain`, `eds.platform.config` | `eds.platform.{run,scheduler,runtime,time,project}`, `eds.adapters`, `eds.runners` |
| `eds.adapters` | `eds.core` | `eds.domains`, `eds.platform`, `eds.runners` |
| `eds.runners` | Everything | Nothing depends on it |

Each rule is enforced by an AST-walking test rather than by convention:

| Test | Asserts |
| --- | --- |
| `test_the_platform_does_not_know_retail_exists` | No import under `eds/platform/` begins with `eds.domains` or `eds.runners` |
| `test_the_retail_domain_does_not_know_the_runner_exists` | The same for `eds/domains/retail/` |
| `test_retail_never_learns_what_ran_it` | Nothing under `eds/domains/retail/` imports the platform's `run`, `scheduler`, `runtime`, `time` or `project` packages at any depth |
| `test_the_runner_opens_no_files_itself` | The boundary touches storage only through the adapter protocols |
| `test_no_temporal_module_reads_a_wall_clock` | No temporal module mentions `datetime.now`, `date.today`, `time.time` or `utcnow` |

A domain does import `eds.platform.domain` and `eds.platform.config` — the
protocol it satisfies and the run-level settings model. Both are declarations,
not runtime.

---

## 6. Data flow

### Snapshot path (CLI)

```
configs/*.yaml ──▶ SimulationConfig
                        │
                        ▼
                   generators ──▶ dict[str, DataFrame] ──▶ validators
                                                              │
                                              (issues? abort, exit 3)
                                                              ▼
                                                    Parquet writer ──▶ output/
```

### Simulation path (platform)

```
Project ─┐
Plan ────┼──▶ SimulationRun ──▶ execute(run, executor)
Clock ───┘                            │
                                      │ per tick, per stage
                                      ▼
                              StageRequest ──▶ RetailExecutor
                                                    │
                    ┌───────────────────────────────┤
                    ▼                               ▼
              read upstream                   read own history
              (stage.requires)                (HISTORY_READ)
                    │                               │
                    └──────────────┬────────────────┘
                                   ▼
                         BusinessContext(date, seed)
                                   ▼
                          domain: advance_day()
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
              generated rows                merged datasets
              (validated)                   (written)
                                                  │
                                                  ▼
                                         Store of Record
                                                  │
                                                  ▼
                                    StageOutput(rows_by_dataset)
                                                  ▼
                              StageResult · events · Progress
```

The two reads are the architecturally interesting part. `stage.requires` comes
from the plan and says what *earlier stages* produced. `HISTORY_READ` comes from
the domain and says what the stage has produced *before* — something a plan
cannot express, because a plan subtracts what a stage produces and would
otherwise be describing a cycle (PADR-016).

---

## 7. Simulation lifecycle

```
create_project(root, name, domain, seed)
      │   writes manifest.json, creates data/
      ▼
create_clock(start, end, tick, calendar)
      │   a value; nothing is running
      ▼
create_run(project, clock, configuration)
      │   resolves the plan from the domain registry
      │   validates that the parts agree — refuses if not
      ▼
execute(run, executor)
      │
      ├── run.validate() → issues?  ──▶ RunFailed, no RunStarted emitted
      │
      ├── RunStarted
      │
      │   while True:
      │     for stage in stages for this tick:
      │        StageStarted
      │        executor.execute(request)
      │           ├─ raises StageExecutionError ──▶ StageFailed, run stops
      │           └─ returns StageOutput
      │        record · persist state · StageCompleted
      │        (AfterStage condition may stop here)
      │     stop condition met?  ──▶ break
      │     clock.is_finished?    ──▶ break
      │     clock = clock.advance()
      │
      ├── cancel stages that never started
      └── RunCompleted or RunFailed
            ▼
      ExecutionReport(result, events, progress)
```

Four properties of this loop are decisions rather than details:

* **State is persisted only after a stage succeeds** (PADR-013). Recording a
  partially-run stage would make a resume skip work never finished; recording a
  failed one would forget the failure.
* **A dry run makes one pass and calls no executor.** A rehearsal answers "what
  would run", and the answer is the same on every tick.
* **A resume honours the project's record on its first tick only** — that is what
  resuming means: pick up where it stopped, then carry on normally.
* **`execute()` never raises for a failed run.** A failure is an outcome, and
  making callers handle both an exception and a status would mean two ways to ask
  one question.

### Multi-tick stage results

A stage running on many ticks produces **one** `StageResult` spanning them, with
rows summed. The runtime contracts forbid two results for one stage, which is why
a stage result carries two dates.

---

## 8. Store of Record

The Store of Record is the project's own complete, readable copy of its data:
`<project>/data/`, one Parquet file per dataset.

It is not a convenience. **A domain derives its entire state from it** — whether
it is founding or continuing, which identifiers have been issued, what the
business currently looks like (PADR-016). There is no checkpoint, no tick counter
and no first-run flag anywhere in EDS, because the data answers all three
questions.

| Property | Detail |
| --- | --- |
| Authority | The authoritative statement of what the enterprise is |
| Completeness | Holds every dataset the domain produces |
| Readability | Must be readable; this is what a domain reads back |
| Format | Snappy-compressed Parquet in v1.0 |
| Location | `Workspace.data_directory` = `<project root>/data` |
| Written by | The runner, through `DatasetWriter` |
| Read by | The runner, through `DatasetReader` |

### Consequences of "data is state"

| Capability | Why it works |
| --- | --- |
| Founding vs continuing | A stage whose own datasets are empty has no history to continue |
| Identity allocation | New identifiers continue past those already issued, which the issued ones record |
| Deterministic replay | A unit of work is addressed by its business *date*, not its position |
| Migration | Copy the directory and the enterprise moves; nothing is left behind |
| Recomputation | Any derived value is a function of history and can be rebuilt |

### Invariant

A domain may cache business history for performance, but persisted business
history remains the single authoritative source of domain state. The test: **if
this were deleted, could it be rebuilt from the persisted data?** If not, the
invariant is broken.

---

## 9. Configuration model

Configuration is split along the platform boundary (PADR-007).

| Model | Lives in | Loaded from | Governs |
| --- | --- | --- | --- |
| `PlatformConfig` | `eds.platform.config` | `simulation.yaml` | Seed, timezone, locale, output directory |
| Retail settings models | `eds.domains.retail.config` | 13 files | Every business volume and rate |
| YAML machinery | `eds.core.config` | — | `read_yaml_mapping`, `build_model`, `ConfigError` |

`SimulationConfig` aggregates one model per feature:

```
SimulationConfig
├── platform: PlatformConfig
├── master_data: MasterDataConfig
├── customers: CustomerConfig
├── journey: JourneyConfig
├── browsing: BrowsingConfig
├── engagement: EngagementConfig
├── commerce: CommerceConfig
├── checkout: CheckoutConfig
├── orders: OrderConfig
├── payments: PaymentConfig
├── shipments: ShipmentConfig
├── returns: ReturnConfig
├── reviews: ReviewConfig
└── evolution: EvolutionConfig
```

Properties:

* Every model is **frozen** and **forbids unknown keys**. A malformed file fails
  at load with a precise error, not part-way through a run.
* `load_config(config_dir)` loads all fourteen. `evolution.yaml` is the one
  optional file — a configuration directory written before Retail could evolve
  still loads, and behaves as it always did (PADR-005).
* Precedence: **CLI flag → YAML → model default.**
* `logging.yaml` has no loader and no consumer. **Not implemented in EDS v1.0.**

---

## 10. Platform architecture decision records

Seventeen records. Sixteen accepted; PADR-017 is a proposed design. Full text in
[`docs/platform/`](platform/README.md).

---

### PADR-001 — Canonical business model

**Purpose.** Fix what the platform may and may not generalise.
**Problem.** A platform serving retail, healthcare and banking is tempted to
model "an entity" or "a transaction" generically.
**Decision.** The platform generalises *mechanics* — determinism, schema
conformance, referential integrity, persistence — and leaves *meaning* entirely
to domains. No base class models a business concept.
**Consequences.** No domain subclasses anything. Abstractions that would fit
none of three industries are never written. Domains carry more code; the platform
carries less risk.
**Affected modules.** `eds.core`, `eds.platform`, all domains.
**References.** PADR-002, PADR-007.

### PADR-002 — Platform-independent domains

**Purpose.** Make the platform's central claim structural rather than aspirational.
**Problem.** Everything was retail-shaped: `eds/generators/` meant retail
generators, `eds/config.py` held retail settings beside platform ones, the
validation framework defaulted to retail master data.
**Decision.** The platform must never import a domain; a domain must never import
the platform's runtime. Dependency direction is enforced by AST-walking tests.
**Consequences.** A second domain requires no platform change. Something must
translate between the two, which is what PADR-014/015 answer. The validation
framework's `declarations` argument became required, with Retail supplying its own
default.
**Affected modules.** `eds.core`, `eds.platform`, `eds.domains`, `eds.runners`.
**References.** PADR-001, PADR-006, PADR-015, PADR-016.

### PADR-003 — Output adapter isolation

**Purpose.** Keep storage out of business code and business out of storage code.
**Problem.** A destination expressed as a `Path` leaks a filesystem into the
contract: a SQL adapter has a connection, Kafka has brokers, REST has a base URL.
None is a `Path`.
**Decision.** No generator may import an adapter and no adapter may import a
generator; they meet only at `polars.DataFrame` and the protocols in
`eds.adapters.base`. The destination is bound when an adapter is *constructed*,
and `write()` returns a `WriteResult` per dataset whose `location` is an opaque
string — a path, a table name, a topic.
**Consequences.** A non-file adapter is expressible. Nothing in the domain knows
where data goes.
**Affected modules.** `eds.adapters`, `eds.domains`, `eds.runners`.
**References.** PADR-015, PADR-016.

### PADR-004 — Platform owns lifecycle

**Purpose.** Settle which settings are a property of a *run* rather than a
business.
**Problem.** Seed, timezone, locale and output location were mixed with business
volumes in one configuration module.
**Decision.** Run-level settings belong to `PlatformConfig` in
`eds.platform.config`, loaded from `simulation.yaml`. Business settings belong to
the domain.
**Consequences.** A domain cannot decide how a run is seeded or where output
goes. `simulation.yaml` holds exactly four keys, asserted by test.
**Affected modules.** `eds.platform.config`, `eds.domains.retail.config`.
**References.** PADR-007, PADR-016.

### PADR-005 — Backward compatibility

**Purpose.** Allow the platform refactor without breaking any existing caller.
**Problem.** Moving retail code out of `eds/generators/`, `eds/validation/`,
`eds/exporters/` and `eds/config.py` would break every import written against the
flat layout.
**Decision.** Each pre-platform path remains as a module that re-exports its new
home explicitly (`X as X`, never `import *`), so mypy sees the names and the
compatibility surface is auditable. The measure of success is stated as a
specific claim: the four commands at seed 42 produce 39 Parquet files whose
SHA-256 digests are identical, file for file, to those produced before the
refactor.
**Consequences.** Old imports resolve to the identical objects, asserted by test.
The shims are a deprecation layer, not a fixture. New optional configuration files
must default rather than fail, so old configuration directories keep working.
**Affected modules.** `eds/config.py`, `eds/domain/`, `eds/generators/`,
`eds/validation/`, `eds/exporters/`.
**References.** ADR-005, ADR-006.

### PADR-006 — The domain protocol describes, it does not execute

**Purpose.** Decide whether the platform may run a domain through the protocol.
**Problem.** `SimulationDomain.generate()` looked natural and would have put
orchestration inside every domain — and forced the platform to define what
"generating" means.
**Decision.** `generate()` was removed on evidence. A domain *describes* itself:
its name, its stages, what each requires and produces. It announces itself to a
registry rather than the platform holding a list of domain names. Registration is
deliberately cheap — generator imports are deferred until something asks about a
stage.
**Consequences.** The platform has no way to execute a domain, which is precisely
why the scheduler takes an executor as an argument (PADR-013) and why the runner
exists (PADR-014). Registration is one import.
**Affected modules.** `eds.platform.domain`, `eds.domains.retail.registry`.
**References.** PADR-008, PADR-013, PADR-014.

### PADR-007 — Configuration ownership

**Purpose.** Decide who owns which settings and who may read them.
**Problem.** One configuration module holding both platform and business settings
makes the platform depend on a domain's vocabulary.
**Decision.** Three homes: `eds.core.config` owns the domain-independent
machinery; `eds.platform.config` owns run-level policy; a domain owns its own
settings models and loaders. Every model is frozen and forbids unknown keys.
**Consequences.** A domain's settings can change without touching the platform.
A bad configuration fails at load with a precise error.
**Affected modules.** `eds.core.config`, `eds.platform.config`,
`eds.domains.retail.config`.
**References.** PADR-004, PADR-005.

### PADR-008 — The execution model plans, it does not execute

**Purpose.** Separate deciding *what should run* from *running it*.
**Problem.** Stage ordering was implicit in the order the CLI commands were
documented.
**Decision.** A plan is derived from the domain's declarations — a
`DependencyGraph` over what each stage requires and produces, topologically
ordered into `PlannedStage`s. The plan is a value and executes nothing. A
requirement nothing produces is an error, so every domain must be closed.
**Consequences.** Ordering is data, not convention. `levels()` exposes which
stages *may* overlap, so parallelism can be added later without touching
ordering. Externally supplied inputs are not expressible — no domain needs them
yet.
**Affected modules.** `eds.platform.execution`.
**References.** PADR-006, PADR-013.

### PADR-009 — The project owns identity and state

**Purpose.** Give a simulated enterprise an identity that outlives a run.
**Problem.** Without one, two runs cannot be known to be the same enterprise, and
nothing can be resumed.
**Decision.** A `Project` is a manifest (immutable identity: id, name, domain,
seed, versions), a `Workspace` (where datasets live), and a `StateStore`
(documents). State is document-oriented — `Mapping[str, Any]` — so a database or
object store is a `StateStore` implementation rather than a rewrite. JSON is
confined to `FileStateStore`.
**Consequences.** The seed lives with the project, so reproducibility is a
property of the enterprise. The scheduler asks the project to write and never
touches a store. `snapshots/` and `logs/` are reserved but not created —
**not implemented in EDS v1.0.**
**Affected modules.** `eds.platform.project`.
**References.** PADR-013, PADR-016.

### PADR-010 — Simulated time is a value, and the platform owns it

**Purpose.** Define what "time" means inside a simulation.
**Problem.** Wall-clock time makes a run unreproducible; a mutable clock makes
advancement a side effect.
**Decision.** Time is a set of immutable values: `SimulationDate` (a `date`
alias, not a wrapper), `Tick(size, unit)`, a one-method `Calendar` protocol,
`TimeRange`, and a frozen `SimulationClock`. Advancing returns a *new* clock.
The calendar is an independent strategy, not part of the clock.
**Consequences.** **Advancement is anchored to the period's start.** A test found
that month ticks are not associative under day-of-month clamping — five one-month
steps from 31 January reach 29 June, one five-month step reaches 30 June — so the
clock computes its position from the start and the elapsed count rather than
stepping. `ticks_elapsed` is derived, never stored. Business calendars carry no
country assumptions.
**Affected modules.** `eds.platform.time`.
**References.** PADR-011, PADR-016.

### PADR-011 — The run binds the primitives so the scheduler takes one argument

**Purpose.** Decide what a scheduler receives.
**Problem.** A scheduler assembling a run from project, plan and clock would have
to validate that they agree — mixing coordination with checking.
**Decision.** A `SimulationRun` binds project + plan + clock + configuration into
one immutable, validated value. `validate()` returns `RunIssue`s;
`create_run(...)` raises. Rules include domain mismatch, empty plan, unknown
target, clock/state mismatch, nothing to resume, unreachable stop condition.
**Consequences.** The scheduler requires exactly one input and never assembles
one. A run that cannot execute is refused before anything starts. **A consequence
found later:** the clock/state rule requires a new run to start exactly where the
last one stopped, so carrying a project forward across separate runs is not
possible — recorded as an open question, and **not implemented in EDS v1.0.**
**Affected modules.** `eds.platform.run`.
**References.** PADR-009, PADR-010, PADR-013.

### PADR-012 — Runtime contracts are deterministic facts

**Purpose.** Define the vocabulary an execution is reported in.
**Problem.** Without one, every runtime component invents its own result type.
**Decision.** Immutable value objects and nothing else: one `ExecutionStatus`
enum with a declared transition table, `Failure` with a `FailureType`,
`StageResult`, `RunResult`, six `ExecutionEvent` kinds as a closed union, and
`Progress`. Invariants are enforced in construction — a terminal-only run status,
`FAILED` if and only if there is a failure, no rows for a skipped stage, no
duplicate stages, no failed stage inside a completed run.
**Consequences.** Contracts refuse to contradict themselves, so the scheduler
needs no consistency checking. **No event bus** — these are values. `Progress`
percentages are `float | None`; an open-ended period has no denominator and a
fabricated one would be worse than none. A run holds one result per stage, which
is why a `StageResult` carries two dates.
**Affected modules.** `eds.platform.runtime`.
**References.** PADR-013.

### PADR-013 — The scheduler coordinates, and the executor arrives as an argument

**Purpose.** Build the first executable component without giving it any knowledge.
**Problem.** The platform has no way to execute a domain (PADR-006), so a
scheduler has nothing to call.
**Decision.** `execute(run, executor)`. The executor is supplied by the caller
through the `StageExecutor` protocol, so the scheduler has no domain dependency —
proved by executing whole runs with a fake. The scheduler is sequential by
design; `ExecutionPlan.levels()` already says what may overlap, so parallelism is
a later change to how one level is executed.
**Consequences.** Every earlier value removed a decision from this module: the
plan is ordered, so no sorting; the clock returns a new clock, so no time state;
the project owns persistence, so no serialisation; the contracts refuse to
contradict themselves, so no checking. What remains is a loop, and a test asserts
the module stays under 220 AST statements. **Not implemented, deliberately:**
retries, recovery, rollback, restart. State is persisted only after a stage
succeeds. The scheduler may not import `polars`, `eds.domains`, `eds.adapters`,
`threading`, `asyncio` or `logging`, and may make no wall-clock call.
**Affected modules.** `eds.platform.scheduler`.
**References.** PADR-006, PADR-011, PADR-012, PADR-014.

### PADR-014 — The runner is a third party to the platform and the domain

**Purpose.** Find a home for the code that teaches a scheduler to run a domain.
**Problem.** It cannot live in the platform (may not import a domain) or in the
domain (may not import the platform). It has nowhere to live in four layers.
**Decision.** A fifth location: `eds/runners/`, one package per domain, the only
place allowed to import both.
**Consequences.** A complete Retail simulation runs end to end through the
platform and produces output **byte-identical to the CLI's**, with no change to
any platform module, any Retail module, any adapter or the CLI. The read list
comes from the plan, so the runner never restates which datasets a stage
consumes. Failures are classified where the knowledge is. **Cost:** the
generate/validate sequence existed twice — CLI and runner — made safe by a test
comparing all 39 files byte for byte. Adding a domain now means adding a runner
too.
**Affected modules.** `eds.runners`.
**References.** PADR-002, PADR-013, PADR-015.

### PADR-015 — The runner is the runtime integration boundary

**Purpose.** Promote PADR-014's discovery to a standing rule.
**Problem.** Running a domain means holding two vocabularies at once — a
`StageRequest`, a `PlannedStage`, a `FailureType` on one side; a business date, a
set of frames, a raised `KeyError` on the other. Neither side may name the other.
**Decision.** `eds/runners/` is the single package permitted to import both, and
is an **anti-corruption layer**: its purpose is to stop each side's vocabulary
leaking into the other. The test for any future addition: *needs both
vocabularies → belongs here; needs one → belongs on that side.*
**Consequences.** The boundary owns translation, invocation, dependency
injection, adapter selection, failure classification and reading the past. It
never owns business rules, orchestration, persistence policy, scheduling or
planning. **Architectural invariant:** business rules accumulating in the Runner
means responsibilities have leaked from the Domain; orchestration accumulating
means they have leaked from the Platform — so growth of the Runner is a signal
requiring review, not normal evolution. Reflection and string-based imports are
forbidden, because every enforcing test works by reading imports.
**Affected modules.** `eds.runners`, and by exclusion every other package.
**References.** PADR-002, PADR-006, PADR-013, PADR-014.

### PADR-016 — Data is domain state

**Purpose.** Settle how a domain knows what it has already done.
**Problem.** Runtime memory dies with the process. Markers, counters, flags and
project metadata all describe *the run* rather than *the enterprise*, and the two
diverge under replay, resume, deterministic execution and migration. Every piece
of execution state a domain keeps also multiplies the states that must be
reasoned about, most of which are representable but unreachable.
**Decision.** Persisted business data is the authoritative representation of
domain state. A domain derives its state exclusively from persisted business
history and stores no execution state. Execution metadata describes execution;
business data describes the enterprise; the two are never substituted.
**Consequences.** Absence of data is the founding condition — no flag. A unit of
work is addressed by its business *date*, not its position, which is what makes
determinism survive a run being divided, interrupted or resumed. **Architectural
invariant:** a domain may cache business history for performance, but persisted
business history remains the single authoritative source of domain state.
**Cost:** reconstruction can be more expensive than remembering, historical
consistency becomes critical, and some derived values are recomputed repeatedly.
**Affected modules.** `eds.domains.retail.temporal`, `eds.adapters`,
`eds.runners.retail`.
**References.** PADR-004, PADR-009, PADR-010, PADR-012, PADR-015; ADR-013,
ADR-014.

### PADR-017 — Enterprise distribution architecture

**Status: Proposed. Not implemented in EDS v1.0.**

**Purpose.** Describe how generated data could be distributed across the several
systems a real enterprise runs on.
**Problem.** A real enterprise has no single database: an ERP owns orders, a CRM
owns customers, a commerce platform owns sessions, and no system holds the whole
picture.
**Decision (proposed).** Enterprise Systems, Distribution Profiles, one owner per
dataset with explicit subscriptions for copies, a computed seam report for
foreign keys that cross system boundaries, and a Distribution Engine composed
above one-way delivery targets.
**Consequences (proposed).** Topology becomes configuration. Delivered data is
deliberately not referentially closed, which makes the Store of Record the only
complete copy.
**Affected modules.** None. Design documentation only.
**References.** [PADR-017](platform/PADR-017-enterprise-distribution-architecture.md),
[P007B design](platform/P007B-destination-adapter-framework.md).

---

## 11. Domain architecture decision records

Fourteen records govern the Retail domain's business rules. Full text in
[`docs/architecture/`](architecture/README.md).

| ADR | Decision | Applies from |
| --- | --- | --- |
| ADR-001 | Derived data preferred over random data | F001 |
| ADR-002 | Generate causality, not coincidence | F003.1 |
| ADR-003 | Configuration preservation | F003.1 |
| ADR-004 | Subtree category matching | F003.3 |
| ADR-005 | Deterministic generation | F001 |
| ADR-006 | Feature immutability | F006 |
| ADR-007 | Single source of financial truth | F006 |
| ADR-008 | Golden record principle | F006 |
| ADR-009 | Derived data over random data (commerce chain) | F006 |
| ADR-010 | State history preferred over mutable state | F006 |
| ADR-011 | One dataset per business entity | F006 |
| ADR-012 | Business document immutability | F006 |
| ADR-013 | History is the state | Temporal evolution |
| ADR-014 | Every dataset declares how it behaves in time | Temporal evolution |

ADR-013 and ADR-014 are the Retail expression of PADR-016: the first says a day
is added to a history rather than replacing it, the second says what "added"
means for each of the 39 datasets. Neither is usable without the other.

### Dataset temporality

Declared per dataset and read by the merge step. A dataset with no declaration
raises rather than defaulting.

| Behaviour | Count | Datasets |
| --- | ---: | --- |
| Static | 13 | Geography, commercial catalogues, supply chain, category tree, brands, products |
| Append-only | 24 | Customers and what registers with them, the whole journey, all commerce |
| Mutable snapshot | 1 | `inventory` |
| Slowly changing | 1 | `customer_loyalty` |

---

## 12. Architecture diagrams

### Layer diagram with enforcement

```
   ┌─────────────────────────────────────────────────────────────┐
   │                       eds.platform                          │
   │  metadata · domain · config                                 │
   │  execution/ · project/ · time/ · run/ · runtime/ · scheduler/│
   │                                                             │
   │  ✗ may not import eds.domains, eds.adapters, eds.runners    │
   └─────────────────────────────────────────────────────────────┘
                                ▲
                                │ imports
   ┌─────────────────────────────────────────────────────────────┐
   │                       eds.runners                           │
   │  retail/executor.py · retail/stages.py                      │
   │                                                             │
   │  ✓ the ONLY package that may import both sides              │
   │  ✗ nothing may import it                                    │
   └─────────────────────────────────────────────────────────────┘
              │ imports                    │ imports
              ▼                            ▼
   ┌────────────────────────┐   ┌────────────────────────┐
   │      eds.domains       │   │      eds.adapters      │
   │  retail/registry.py    │   │  base.py (protocols)   │
   │  retail/domain/        │   │  parquet/              │
   │  retail/generators/    │   │                        │
   │  retail/temporal/      │   │  = Store of Record     │
   │  retail/validation/    │   │                        │
   │                        │   │  ✗ no generator may    │
   │  ✗ may not import the  │   │    import an adapter   │
   │    platform's runtime  │   │                        │
   └────────────────────────┘   └────────────────────────┘
              │                            │
              └──────────┬─────────────────┘
                         ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                        eds.core                             │
   │  schema · frames · random_streams · config · validation/     │
   │                                                             │
   │  ✗ may import nothing inside eds except eds.version         │
   └─────────────────────────────────────────────────────────────┘
```

### One stage of one business day

```
  scheduler                runner                  domain            adapter
      │                      │                       │                  │
      │─ StageRequest ──────▶│                       │                  │
      │   stage, date,       │─ read stage.requires ─┼─────────────────▶│
      │   run_id, project_id,│─ read HISTORY_READ ───┼─────────────────▶│
      │   seed, data_dir     │                       │                  │
      │                      │─ BusinessContext ────▶│                  │
      │                      │   (date, seed)        │  founding or     │
      │                      │                       │  continuing?     │
      │                      │◀─ generated, merged ──│  ── from the     │
      │                      │                       │     data alone   │
      │                      │─ validate generated ──│                  │
      │                      │─ write merged ────────┼─────────────────▶│
      │◀─ StageOutput ───────│                       │                  │
      │   rows_by_dataset    │                       │                  │
```

### Where a failure is classified

```
   domain raises              runner classifies          scheduler records
   ─────────────              ─────────────────          ─────────────────
   KeyError, ValueError  ──▶  GENERATION           ──▶   Failure(type, msg,
   validation issues     ──▶  VALIDATION                  stage, cause)
   AdapterError (read)   ──▶  DEPENDENCY           ──▶   StageFailed event
   AdapterError (write)  ──▶  PERSISTENCE          ──▶   StageResult(FAILED)
   unknown stage         ──▶  CONFIGURATION
   anything else         ──▶  INTERNAL  (scheduler's own catch-all)
```

---

## 13. Dependency diagrams

### Permitted imports

```
                      ┌──────────────┐
                      │ eds.version  │
                      └──────┬───────┘
                             ▼
                      ┌──────────────┐
                      │   eds.core   │
                      └──┬────┬───┬──┘
             ┌───────────┘    │   └───────────┐
             ▼                ▼               ▼
     ┌──────────────┐  ┌─────────────┐ ┌──────────────┐
     │ eds.platform │  │ eds.domains │ │ eds.adapters │
     └──────┬───────┘  └──────┬──────┘ └──────┬───────┘
            │  ▲              │               │
            │  └──────────────┘               │
            │   (domain → platform.domain,    │
            │    platform.config ONLY)        │
            │                                 │
            └──────────┬──────────────────────┘
                       ▼
                ┌──────────────┐
                │ eds.runners  │  imports all three
                └──────────────┘

     ┌──────────────┐
     │   eds.cli    │  imports eds.core, eds.domains, eds.adapters
     └──────────────┘  (predates the platform — PADR-005)
```

### Forbidden imports, and the test that forbids each

| Forbidden | Test |
| --- | --- |
| `eds.platform` → `eds.domains` | `test_the_platform_does_not_know_retail_exists` |
| `eds.platform` → `eds.runners` | same |
| `eds.domains` → `eds.runners` | `test_the_retail_domain_does_not_know_the_runner_exists` |
| `eds.domains` → `eds.platform.{run,scheduler,runtime,time,project}` | `test_retail_never_learns_what_ran_it` |
| `eds.core` → anything in `eds` but `eds.version` | package-layout tests |
| Generators → adapters | package-layout tests |
| `eds.platform.scheduler` → `polars`, `threading`, `asyncio`, `logging` | scheduler tests |

### Runtime dependency direction within the platform

```
  scheduler ──▶ run ──▶ project ──▶ ( StateStore )
      │          │  ├──▶ execution
      │          │  └──▶ time
      ├──▶ runtime
      └──▶ ( StageExecutor )   ← supplied by the caller, never imported

  time ──▶ project   ONLY in time/persistence.py, the single bridge module
```

`eds.platform.time.persistence` is the only module in `eds.platform.time` that
knows projects exist. A test enforces it by AST, so the time model stays usable
without a project.

---

## 14. Glossary

Defined in the [Handbook glossary](01_Handbook.md#19-glossary) and used unchanged
throughout. Terms specific to this document:

| Term | Meaning |
| --- | --- |
| **Anti-corruption layer** | A boundary whose purpose is to stop two vocabularies leaking into each other. `eds.runners` |
| **Closed union** | A `type X = A \| B \| C` where a consumer must interpret every kind |
| **Contract version** | `PLATFORM_CONTRACT_VERSION` — the version of the domain and adapter protocols |
| **Dependency graph** | The requires/produces relation from which a plan is ordered |
| **Disposition** | Proposed delivery vocabulary (replace / append / upsert). Not implemented in EDS v1.0 |
| **Execution metadata** | The platform's record of a run: completed stages, clock position, outcomes |
| **PADR** | Platform Architecture Decision Record. Governs where code may live |
| **ADR** | Architecture Decision Record. Governs Retail's business rules |
| **Seam** | Proposed term for a foreign key crossing a system boundary. Not implemented in EDS v1.0 |
| **Stage identifier** | `"<domain>:<stage>"`, e.g. `retail:commerce` |
