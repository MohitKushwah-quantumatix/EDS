# Platform Architecture

## The layers

```
eds/
├── core/                    Shared infrastructure. Knows no business, no storage.
│   ├── schema.py            Dataset, ForeignKey - the declarative schema
│   ├── frames.py            build_frame, empty_frame, format_code
│   ├── random_streams.py    make_rng, make_faker, stream_seed, resolve_seed
│   ├── config.py            ConfigError, YAML loading. Mechanism only
│   └── validation/
│       ├── issues.py        ValidationIssue, ValidationError
│       └── referential.py   Schema, key and foreign-key checks
│
├── platform/                What it means to run a simulation.
│   ├── metadata.py          PlatformMetadata, contract version
│   ├── config.py            PlatformConfig - seed, locale, output directory
│   ├── project.py           Project
│   ├── domain.py            SimulationDomain, DomainStage, registry
│   ├── execution/           Planning. Answers "what should run?"
│   │   ├── graph.py             DependencyGraph, derived from data flow
│   │   ├── plan.py              ExecutionPlan, PlannedStage
│   │   ├── validation.py        Plan validation rules
│   │   └── planner.py           build_execution_plan, plan_domain
│   ├── project/             Durable identity and state. Stores; never runs
│   │   ├── manifest.py          ProjectManifest - immutable identity
│   │   ├── state.py             SimulationState - stored, never advanced
│   │   ├── workspace.py         Workspace layout
│   │   ├── store.py             StateStore protocol, FileStateStore
│   │   ├── versions.py          Manifest, state and contract versions
│   │   └── project.py           Project handle, create/open
│   ├── time/                What time means. Defines; never advances itself
│   │   ├── dates.py             SimulationDate, strict ISO 8601 parsing
│   │   ├── time_range.py        TimeRange - the declared period
│   │   ├── tick.py              Tick, TickUnit - one logical advancement
│   │   ├── calendar.py          Calendar protocol, BusinessCalendar
│   │   ├── clock.py             SimulationClock - immutable, derived count
│   │   └── persistence.py       The only bridge to eds.platform.project
│   ├── run/                 Binds project, plan and clock. Validates; never runs
│   │   ├── mode.py              RunMode - which stages
│   │   ├── stop.py              A closed set of stop conditions
│   │   ├── configuration.py     RunConfiguration - the portable half
│   │   └── run.py               SimulationRun, create_run
│   ├── runtime/             What happened. Facts only, no behaviour
│   │   ├── status.py            ExecutionStatus and its declared transitions
│   │   ├── failure.py           Failure, FailureType, ExecutionWarning
│   │   ├── results.py           RunResult, StageResult
│   │   ├── events.py            Six execution events, ordered by sequence
│   │   └── progress.py          Progress - the one in-flight contract
│   ├── scheduler/           Runs it. The first executable component
│   │   ├── executor.py          StageExecutor protocol - supplied by the caller
│   │   ├── report.py            ExecutionReport - result, events, progress
│   │   └── scheduler.py         execute(run, executor)
│   └── state.py             Placeholder - not implemented
│
├── domains/                 The businesses being simulated.
│   └── retail/
│       ├── registry.py      RetailDomain - the concrete SimulationDomain
│       ├── config.py        Retail settings models and loaders
│       ├── domain/          Entity schemas and enums
│       ├── generators/      Business event generators
│       ├── temporal/        What one simulated day does to the business
│       └── validation/      Retail business rules
│
├── adapters/                Where output goes.
│   ├── base.py              DatasetWriter, DatasetReader, WriteResult
│   └── parquet/             reader, writer, ParquetAdapter
│
├── runners/                 Integration. Imports both sides; neither imports it.
│   └── retail/
│       ├── executor.py      RetailExecutor - the StageExecutor the scheduler runs
│       └── stages.py        Runs a stage for a date, and classifies failures
│
└── cli/                     Unchanged. Four commands, same behaviour.
```

## Layer responsibilities

### core

Owns everything that is true regardless of which business is being simulated
and where the output goes.

**May depend on:** nothing inside `eds` except `eds.version`.

The one thing this cost: `validate_referential_integrity` used to default its
`declarations` argument to the retail master datasets, which made the
validation framework import the retail registry. In core that argument is now
required. Retail supplies the old default in
`eds/domains/retail/validation/referential.py`, so every existing caller —
including `validate_master_data`, which relies on it — behaves exactly as
before.

### platform

Owns simulation lifecycle: identity, metadata, the registry a domain plugs
into, the execution model that turns a domain's declarations into a validated
plan (PADR-008), what time means (PADR-010), and the run that binds those three
into one validated configuration (PADR-011), the contracts execution is
reported in (PADR-012), and the scheduler that runs it (PADR-013). Later
phases add the growth engine here (PADR-004).

The execution model plans; it does not execute. It may not import `polars`,
`eds.domains`, `eds.adapters` or `eds.core`, and a test enforces that.

The project model stores; it does not run. It may not import `polars`,
`eds.domains`, `eds.adapters` or `eds.platform.execution` — the last so that
state cannot start interpreting plans (PADR-009). No domain may import
`eds.platform.project`, which is what keeps persistence out of business code.

The time model defines; it does not advance itself. Beyond the same bans it may
not import `threading` or `asyncio`, and no module in it may call `now()`,
`today()`, `utcnow()` or `sleep()` — a single wall-clock read would make output
depend on when a run happened (ADR-005). Only `persistence.py` knows
`eds.platform.project` exists, and the dependency runs one way: no project
module imports the time model. No domain may import `eds.platform.time`.

The run model binds; it does not execute. It is the **only** module permitted
to depend on the execution model, the project and the time model at once — that
is its purpose — and the dependency runs strictly one way: a test asserts that
none of those three imports `eds.platform.run` (PADR-011). It may not import
`polars`, `eds.domains`, `eds.adapters`, `threading` or `asyncio`, and no
domain may import it.

The runtime contracts describe; they contain no behaviour at all. They are the
platform's most isolated package: the only `eds` import permitted anywhere in
them is `eds.platform.time.dates`, so a stored result can be read back on a
machine where no plan, project, clock or run exists. Identifiers are opaque
strings. No wall-clock call is permitted, which is what makes two runs of one
simulation produce equal results (PADR-012).

The scheduler coordinates; it knows no business. It is the only module that
executes anything, and it cannot execute a domain: a `StageExecutor` is
supplied by the caller, because the platform deliberately has no way to run one
(PADR-006, PADR-013). It may not import `polars`, `eds.domains`, `eds.adapters`,
`threading`, `asyncio` or `logging`, may make no wall-clock call, and no domain
may import it.

### runners

The **runtime integration boundary**, and not part of the platform or of any
domain. One package per domain, and the only place allowed to import both — an
anti-corruption layer whose purpose is to stop either side's vocabulary leaking
into the other (PADR-015).

**May depend on:** everything. **Nothing may depend on it** — a test asserts
that neither `eds/platform/` nor `eds/domains/` mentions `eds.runners`.

`eds/runners/retail/` holds the `StageExecutor` the scheduler runs. It reads
what `PlannedStage.requires` declares and what `HISTORY_READ` says the stage
must be shown of the past, asks the domain to run the stage for the request's
date, writes what changed through an adapter, and reports row counts. It orders
nothing, advances nothing, decides nothing about a business and opens no files
(PADR-014).

Generation itself is *not* here. P006.1 had to put it here because Retail had
no notion of being run; ADR-013 gave it one, so what remains in this layer is
the one thing only it can do — telling a generator that raised from data that
failed validation from a disk that would not accept a write.

That correction is the precedent PADR-015 records: work that turns out to need
only one of the two vocabularies moves to that side. A runner that starts
needing to orchestrate belongs in the scheduler; one that starts deciding what a
business does belongs in the domain.

**May depend on:** `core`.

A domain derives its current business state from the business data it has
persisted, and keeps no record of having run: absence of data is the founding
condition, and a unit of work is addressed by its business moment rather than by
its position in a sequence (PADR-016). That is what makes a domain replayable and
resumable without any bookkeeping of its own.

`eds/domains/retail/temporal/` is what makes Retail a simulation rather than a
snapshot. It holds the domain's own notion of a business date, the declaration
of what each of the thirty-nine datasets does when a day passes, the rules that
keep identifiers stable as the business grows, and the entry point that runs one
stage for one date — founding its datasets if they are empty and continuing them
if they are not (ADR-013, ADR-014). It knows nothing of clocks, ticks, runs,
plans, projects or schedulers: it is told a date.

Nothing in Retail depends on the platform's runtime today, and the CLI does not
route through the domain registry. That is deliberate — routing Retail through
a registry it is the only member of would have been change for its own sake,
and change is exactly what PADR-005 forbids. The registry exists so the
*second* domain has something to join.

### domains

Owns business meaning: which entities exist, what a valid one looks like, how
events produce records.

**May depend on:** `core`. **May not depend on:** `adapters`.

A domain never learns where its output goes. `generate_order_data` returns
frames; something else decides they become Parquet.

### adapters

Owns persistence. Parquet is the only implementation.

**May depend on:** `core`. **May not depend on:** `domains`.

`ParquetAdapter` is a binding, not a rewrite: it wraps the existing
`write_datasets` and `read_datasets` behind the protocols. The CLI still calls
those functions directly, so the write path is byte-for-byte the one that
produced every dataset to date.

### cli

Composes the layers. This is the only place that legitimately knows about a
domain *and* an adapter at once, because composition is its job.

## Dependency direction

| Layer | May import | May not import |
| --- | --- | --- |
| `core` | — | `platform`, `domains`, `adapters` |
| `platform` | `core` | `domains`, `adapters` |
| `domains` | `core` | `adapters` |
| `adapters` | `core` | `domains` |
| `cli` | all | — |

These are not documentation. `eds/tests/test_platform_layout.py` parses the
AST of every module in each layer and fails if an import crosses a forbidden
boundary, so the direction is enforced on every run.

## Compatibility layer

Every pre-platform import path still resolves. `eds/domain/`,
`eds/generators/`, `eds/validation/`, `eds/exporters/` and `eds/config.py`
remain as modules that re-export their new homes explicitly:

```python
# eds/generators/commerce/orders.py
"""Backward-compatible alias. ..."""

from eds.domains.retail.generators.commerce.orders import (
    OrderData as OrderData,
    REQUIRED_ORDER_DATASETS as REQUIRED_ORDER_DATASETS,
    generate_order_data as generate_order_data,
)
```

The re-exports are explicit `X as X` rather than `import *` so that mypy sees
them and so that the compatibility surface is auditable. A test asserts that
every name a new module defines is *the identical object* when reached through
the old path — not merely present.

These are a deprecation layer, not a permanent fixture. See the
[roadmap](03_Roadmap.md) for the removal path.

## Where a second domain plugs in

```python
from eds.platform.domain import register_domain


class HealthcareDomain:
    name = "healthcare"
    dataset_names = ("patients", "encounters", "claims")

    def generate(self): ...


register_domain(HealthcareDomain())
```

Requires: a new package under `eds/domains/`, its own `configs/*.yaml`, and its
own schema declarations. Requires no change to `core`, `platform`, `adapters`
or `cli`.
