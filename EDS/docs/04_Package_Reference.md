# Enterprise Data Simulator — Package Reference

**EDS v1.0 · Official documentation · Document 4 of 5**

Audience: developers. Purpose: reference every public package.

Companion documents: [Handbook](01_Handbook.md) ·
[Architecture Reference](02_Architecture_Reference.md) ·
[Maintainer Guide](03_Maintainer_Guide.md) ·
[Developer Quick Start](05_Developer_Quick_Start.md) ·
[Documentation index](README.md)

Every name listed appears in the corresponding module's `__all__`. Names not
listed are private and may change.

---

## Table of contents

- [Package map](#package-map)
- [`eds`](#eds)
- [`eds.core`](#edscore)
- [`eds.core.validation`](#edscorevalidation)
- [`eds.platform`](#edsplatform)
- [`eds.platform.execution`](#edsplatformexecution)
- [`eds.platform.project`](#edsplatformproject)
- [`eds.platform.time`](#edsplatformtime)
- [`eds.platform.run`](#edsplatformrun)
- [`eds.platform.runtime`](#edsplatformruntime)
- [`eds.platform.scheduler`](#edsplatformscheduler)
- [`eds.domains.retail`](#edsdomainsretail)
- [`eds.domains.retail.temporal`](#edsdomainsretailtemporal)
- [`eds.adapters`](#edsadapters)
- [`eds.runners.retail`](#edsrunnersretail)
- [`eds.cli`](#edscli)
- [Compatibility packages](#compatibility-packages)
- [Reserved packages](#reserved-packages)
- [Package diagram](#package-diagram)

---

## Package map

| Package | Modules | Public names | Role |
| --- | ---: | ---: | --- |
| `eds.core` | 4 | 13 | Shared vocabulary |
| `eds.core.validation` | 2 | 7 | Validation framework |
| `eds.platform` | 3 | 14 | Lifecycle root: metadata, domain protocol, config |
| `eds.platform.execution` | 5 | 11 | Planning |
| `eds.platform.project` | 7 | 25 | Identity and state |
| `eds.platform.time` | 7 | 32 | Simulated time |
| `eds.platform.run` | 5 | 13 | The scheduler's single input |
| `eds.platform.runtime` | 7 | 23 | Execution vocabulary |
| `eds.platform.scheduler` | 3 | 6 | Execution |
| `eds.domains.retail` | 2 | 2 | Domain description |
| `eds.domains.retail.temporal` | 8 | 10 | Evolution over simulated time |
| `eds.adapters` | 1 + parquet | 6 | Store of Record |
| `eds.runners.retail` | 2 | 4 | Integration boundary |
| `eds.cli` | 2 | 4 | Command line |

---

## `eds`

**Purpose.** The distribution root. Holds the version and the layer packages.

**Public API**

```python
from eds.version import __version__  # "0.1.0"
```

`eds/version.py` is public API and is also read by the build backend, so the
distribution version and the runtime version cannot drift apart.

**Extension points.** None. `eds/py.typed` marks the package as typed.

---

## `eds.core`

**Purpose.** Everything true regardless of which business is simulated and where
output goes.

**Responsibilities.** Dataset declarations; schema-conformant frame construction;
deterministic random streams; YAML loading and model building; the validation
framework.

**Depends on.** `eds.version` only.
**Used by.** Every other package.

### Public API

| Module | Names |
| --- | --- |
| `eds.core.schema` | `Dataset`, `ForeignKey` |
| `eds.core.frames` | `build_frame`, `empty_frame`, `format_code` |
| `eds.core.random_streams` | `make_rng`, `make_faker`, `resolve_seed`, `stream_seed` |
| `eds.core.config` | `DEFAULT_CONFIG_DIR`, `ConfigError`, `build_model`, `read_yaml_mapping` |

### Important classes

**`Dataset`** — the single declaration everything else reads.

```python
Dataset(
    name="orders",
    columns={"order_id": pl.Int64(), ...},   # name → polars dtype
    primary_key="order_id",
    unique_columns=("order_number", "checkout_id", "cart_id"),
    foreign_keys=(ForeignKey("customer_id", "customers", "customer_id"), ...),
)
```

Validation, renumbering and (in a time-aware domain) merging all read this rather
than restating it. **Per-column nullability is not expressible. Not implemented in
EDS v1.0** — only `ForeignKey(nullable=True)` exists.

**`ForeignKey`** — `(column, references, referenced_column, nullable=False)`.

### Important functions

| Function | Contract |
| --- | --- |
| `build_frame(dataset, columns)` | Builds a frame conforming to the declaration. Column order and dtypes come from `Dataset` |
| `empty_frame(dataset)` | A zero-row frame with the declared schema |
| `format_code(prefix, number, width=6)` | `"SKU-000042"`. Raises `ValueError` on a negative number |
| `stream_seed(seed, stream)` | First 8 bytes of `sha256(f"{seed}:{stream}")`. Stable across processes and Python versions — unlike `hash()` |
| `make_rng(seed, stream)` | A `random.Random` for one named stream |
| `make_faker(seed, stream, locale)` | An independently seeded `Faker` |
| `resolve_seed(seed)` | Returns the seed, or draws entropy when it is `None` |
| `read_yaml_mapping(path)` | Parses a YAML mapping. Raises `ConfigError` |
| `build_model(model, mapping, path)` | Builds a Pydantic model, reporting the file on failure |

### Why named streams exist

Every generator draws from its own stream derived from the run seed. Independent
streams mean **adding or resizing one dataset does not shift the values of any
other**, and generators can run in any order and still reproduce byte-identical
output.

**Extension points.** `Dataset` and `ForeignKey` are the vocabulary any new domain
declares in. `stream_seed` is the seeding contract any generator must use.

---

## `eds.core.validation`

**Purpose.** Domain-independent validation machinery.

**Depends on.** `eds.core.schema`, `polars`.
**Used by.** Every domain's `validation/` package.

### Public API

| Module | Names |
| --- | --- |
| `eds.core.validation.issues` | `ValidationIssue`, `ValidationError`, `format_issues` |
| `eds.core.validation.referential` | `validate_schema`, `validate_primary_key`, `validate_foreign_keys`, `validate_referential_integrity` |

**`ValidationIssue`** — `(dataset, rule, detail)`, rendered as
`[orders] duplicate_identifier: …`. Validators **return** issues; they do not
raise. The caller decides what a failure means.

**`validate_referential_integrity(datasets, declarations)`** — the `declarations`
argument is **required**. It used to default to Retail's master datasets, which
made the framework import the retail registry; PADR-002 removed that. Retail
supplies its own default in `eds/domains/retail/validation/referential.py`.

**Extension points.** Return `list[ValidationIssue]` from any new rule and it
composes with everything else.

---

## `eds.platform`

**Purpose.** What it means to *run* a simulation. Knows no business.

**Depends on.** `eds.core`.
**Used by.** `eds.runners`, and `eds.domains` for the description protocol only.

### Public API

| Module | Names |
| --- | --- |
| `eds.platform.metadata` | `PLATFORM_NAME`, `PLATFORM_CONTRACT_VERSION`, `PlatformMetadata`, `platform_metadata` |
| `eds.platform.domain` | `SimulationDomain`, `DomainStage`, `register_domain`, `get_domain`, `resolve_domain`, `list_domains`, `available_domains` |
| `eds.platform.config` | `PlatformConfig`, `PLATFORM_CONFIG_FILE`, `load_platform_config` |

### Important interfaces

**`SimulationDomain`** — a `Protocol`. A domain **describes**; it does not execute
(PADR-006).

```python
@runtime_checkable
class SimulationDomain(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def stages(self) -> tuple[DomainStage, ...]: ...
    @property
    def dataset_names(self) -> tuple[str, ...]: ...
```

There is deliberately **no `generate()`**. The platform has no way to execute a
domain, which is why the scheduler takes an executor as an argument.

**`DomainStage`** — `(name, requires, produces)`. `requires` must be produced by
an earlier stage; `produces` is what the stage writes.

**`PlatformConfig`** — frozen, `extra="forbid"`:

| Field | Default |
| --- | --- |
| `seed` | `42` — `None` means non-deterministic |
| `timezone` | `"UTC"` |
| `locale` | `"en_US"` |
| `output_directory` | `Path("output")` |

### The registry

A domain announces itself with `register_domain(MyDomain())` at import time. The
platform holds no list of domain names, which is what keeps it free of them.

**Extension points.** `SimulationDomain` + `register_domain` is how a second
domain joins. `PLATFORM_CONTRACT_VERSION` versions the domain and adapter
protocols.

**Not implemented in EDS v1.0.** `eds/platform/state.py` is a placeholder.

---

## `eds.platform.execution`

**Purpose.** Turn a domain's declarations into a validated, ordered plan. Plans
only; executes nothing (PADR-008).

**Depends on.** `eds.platform.domain`.
**Used by.** `eds.platform.run`, `eds.runners`.

### Public API

`DependencyGraph`, `ExecutionPlan`, `PlannedStage`, `PlanningIssue`,
`PlanningError`, `PlanValidationError`, `plan_domain`, `build_execution_plan`,
`validate_stages`, `assert_plannable`, `stage_id`

### Important classes

**`PlannedStage`** — `(stage_id, domain, name, requires, produces, depends_on)`.
`stage_id` is `"<domain>:<stage>"`, e.g. `retail:commerce`.

**`ExecutionPlan`** — ordered stages plus:

| Member | Returns |
| --- | --- |
| `stages` | The stages in dependency order |
| `stage_ids` | Their identifiers |
| `levels()` | Groups of stages that **may** overlap |
| `len(plan)` | Stage count |

`levels()` exists so parallelism can be added later by changing how one level is
executed, without touching ordering, persistence, events or results.

### Usage

```python
from eds.platform.execution import plan_domain

plan = plan_domain("retail")
for stage in plan.stages:
    print(stage.stage_id, "requires", stage.requires)
```

`plan_domain(name, targets=...)` narrows a plan to named stages and their
dependencies.

**A requirement nothing produces is an error**, so every domain must be closed.
Externally supplied inputs are **not implemented in EDS v1.0**.

---

## `eds.platform.project`

**Purpose.** A durable identity for a simulated enterprise, and somewhere to
record progress (PADR-009).

**Depends on.** `eds.core`, `eds.platform.metadata`.
**Used by.** `eds.platform.run`, `eds.platform.scheduler`, `eds.runners`.

### Public API

`Project`, `create_project`, `open_project`, `ProjectManifest`, `SimulationState`,
`Workspace`, `StateStore`, `FileStateStore`, `Document`, `ProjectError`,
`ProjectExistsError`, `ProjectIssue`, `CorruptDocumentError`, `MANIFEST_KEY`,
`STATE_KEY`, `MANIFEST_VERSION`, `STATE_VERSION`, `DATA_DIRECTORY`,
`SNAPSHOTS_DIRECTORY`, `LOGS_DIRECTORY`

### Important classes

**`Project`** — frozen: `(manifest, workspace, store)`.

```python
project = create_project(Path("./shop"), name="Shop", domain="retail", seed=42)
project = open_project(Path("./shop"))

state = project.read_state()
project.write_state(replace(state, current_date=date(2026, 1, 2)))
```

**`ProjectManifest`** — immutable identity: `project_id`, `name`, `domain`,
`seed`, `created_at`, `platform_version`, `platform_contract_version`,
`manifest_version`.

**`SimulationState`** — `current_date`, `completed_stages`, `last_identifiers`,
`state_version`. Rejects a stage recorded twice: that means a lost write or a
scheduler bug, and accepting it would hide both.

**`Workspace`** — `root`, and:

| Property | Path | Created |
| --- | --- | --- |
| `data_directory` | `<root>/data` | Yes |
| `snapshots_directory` | `<root>/snapshots` | **No — reserved. Not implemented in EDS v1.0** |
| `logs_directory` | `<root>/logs` | **No — reserved. Not implemented in EDS v1.0** |

**`StateStore`** — a `Protocol` over documents:

```python
@runtime_checkable
class StateStore(Protocol):
    def exists(self, key: str) -> bool: ...
    def read(self, key: str) -> dict[str, Any]: ...
    def write(self, key: str, document: Document) -> None: ...
```

`Document = Mapping[str, Any]`. State is document-oriented so a database or object
store is an implementation rather than a rewrite. **JSON is confined to
`FileStateStore`**, which writes `<key>.json` with sorted keys and an indent —
stable bytes for the same content.

**Extension points.** `StateStore` for documents elsewhere. `Workspace` is
filesystem-shaped because adapters write by location.

---

## `eds.platform.time`

**Purpose.** Define what time *means* inside a simulation. Values only; nothing
executes (PADR-010).

**Depends on.** `eds.core`. `time/persistence.py` alone also imports
`eds.platform.project` — the single bridge module, enforced by an AST test.
**Used by.** `eds.platform.run`, `eds.platform.scheduler`.

### Public API

`SimulationDate`, `parse_simulation_date`, `MIN_SIMULATION_DATE`,
`MAX_SIMULATION_DATE`, `Tick`, `TickUnit`, `DAILY`, `WEEKLY`, `MONTHLY`,
`YEARLY`, `Calendar`, `ContinuousCalendar`, `BusinessCalendar`,
`next_business_day`, `previous_business_day`, `add_business_days`,
`business_days_between`, `MAX_CALENDAR_SEARCH_DAYS`, `TimeRange`,
`SimulationClock`, `create_clock`, `clock_from_state`, `state_with_clock`, and
the error hierarchy (`TimeError`, `InvalidDateError`, `InvalidTickError`,
`InvalidTimeRangeError`, `CalendarError`, `InvalidAdvancementError`,
`TimeOverflowError`, `SimulationEndedError`)

### Important classes

**`SimulationClock`** — frozen: `(time_range, current_date, tick, calendar)`.

```python
clock = create_clock(date(2026, 1, 1), end=date(2026, 3, 31), tick=DAILY)
later = clock.advance()  # a NEW clock
much_later = clock.advance(10)
```

| Member | Meaning |
| --- | --- |
| `advance(count=1)` | Returns a new clock. Never mutates |
| `ticks_elapsed` | **Derived**, never stored |
| `is_finished` | Whether the period is exhausted |
| `start`, `end` | The period's bounds |

**Advancement is anchored to the period's start.** A test found that month ticks
are not associative under day-of-month clamping — five one-month steps from 31
January reach 29 June; one five-month step reaches 30 June. The clock therefore
computes its position from `(start, ticks_elapsed + count)` rather than stepping,
so stepping and jumping always agree.

**`Tick`** — `(size, unit)`. `TickUnit` is `DAY`, `WEEK`, `MONTH`, `YEAR`,
`BUSINESS_DAY`. Constants: `DAILY`, `WEEKLY`, `MONTHLY`, `YEARLY`.

**`Calendar`** — a one-method `Protocol`:

```python
@runtime_checkable
class Calendar(Protocol):
    @property
    def name(self) -> str: ...
    def is_business_day(self, day: date) -> bool: ...
```

`ContinuousCalendar` (every day) is the default. `BusinessCalendar(weekend_days,
holidays, label)` carries **no country assumptions** — the caller supplies them.

**`SimulationDate`** is a `type` alias for `date`, not a wrapper.
`parse_simulation_date` accepts only strict `YYYY-MM-DD`.

**Extension points.** `Calendar` for a region's or industry's working week.
`TickUnit` for a new step size.

---

## `eds.platform.run`

**Purpose.** Bind project + plan + clock + configuration into one immutable,
validated value, so the scheduler takes a single argument (PADR-011).

**Depends on.** `eds.platform.{project,execution,time}`.
**Used by.** `eds.platform.scheduler`.

### Public API

`SimulationRun`, `create_run`, `RunConfiguration`, `RunMode`, `StopCondition`,
`EndOfPeriod`, `AfterTicks`, `AfterStage`, `STOP_CONDITION_KINDS`,
`stop_condition_from_document`, `RunIssue`, `RunError`, `RunValidationError`

### Important classes

**`SimulationRun`** — frozen: `(run_id, project, plan, clock, configuration)`.

| Member | Returns |
| --- | --- |
| `validate()` | `list[RunIssue]` — empty when executable |
| `assert_valid()` | Raises `RunValidationError` |
| `read_state()` | The project's recorded state |
| `remaining_stages()` | Stages not yet recorded as completed |
| `stop_condition`, `is_dry_run`, `mode` | Convenience accessors |
| `to_document()` | One-way serialisation |

**`create_run(project, clock, configuration=None, plan=None, run_id=None)`**
resolves the plan from the registry, validates, and raises on any issue.

### Validation rules

| Rule | Fires when |
| --- | --- |
| `domain_mismatch` | The plan's domain is not the project's |
| `empty_plan` | The plan has no stages |
| `unknown_target` | A target names a stage not in the plan |
| `clock_state_mismatch` | The clock is not where the project stopped |
| `nothing_to_resume` | Every stage is already recorded as completed |
| `unreachable_stop_condition` | `EndOfPeriod` on an open-ended clock |
| `unknown_stop_stage` | `AfterStage` names a stage not in the plan |
| `unreadable_state` | The state document cannot be read |

`clock_state_mismatch` is why a project cannot be carried forward by a second run
starting on the next date. **Not implemented in EDS v1.0** — run the whole period
in one call.

**`RunConfiguration`** — `(mode, targets, stop_condition, dry_run)`. Round-trips
to and from a document.

**`RunMode`** — `FULL`, `TARGETED`, `RESUME`; `accepts_targets` says which take
targets.

**`StopCondition`** — a **closed union**: `EndOfPeriod | AfterTicks | AfterStage`.
Closed because every consumer must interpret every kind.

---

## `eds.platform.runtime`

**Purpose.** The vocabulary an execution is reported in. Facts, never behaviour
(PADR-012).

**Depends on.** `eds.core` only.
**Used by.** `eds.platform.scheduler`, `eds.runners`.

### Public API

`ExecutionStatus`, `TERMINAL_STATUSES`, `STATUS_TRANSITIONS`,
`is_valid_transition`, `require_valid_transition`, `InvalidStatusTransitionError`,
`RuntimeContractError`, `FailureType`, `Failure`, `ExecutionWarning`,
`StageResult`, `RunResult`, `Progress`, `ExecutionEvent`, `RunStarted`,
`RunCompleted`, `RunFailed`, `StageStarted`, `StageCompleted`, `StageFailed`,
`EXECUTION_EVENT_KINDS`, `in_sequence`, `execution_event_from_document`

### Important classes

**`ExecutionStatus`** — one enum for runs and stages: `PENDING`, `RUNNING`,
`COMPLETED`, `FAILED`, `SKIPPED`, `CANCELLED`. Legal transitions are a declared
table; an illegal one raises and the message says what *would* have worked.

**`FailureType`** — `CONFIGURATION`, `GENERATION`, `VALIDATION`, `PERSISTENCE`,
`DEPENDENCY`, `INTERNAL`.

**`StageResult`** — `(stage_id, status, start_date, end_date, rows_by_dataset,
failure, warnings)`. **Two dates** because a stage that ran on many ticks gets one
result spanning them, with rows summed — a run may not hold two results for one
stage.

**`RunResult`** — `(run_id, project_id, status, start_date, end_date,
started_tick, finished_tick, stages, failure, warnings)`.

Invariants enforced in construction:

* the status must be terminal;
* `FAILED` if and only if there is a failure;
* a skipped or cancelled stage holds no rows;
* no duplicate stage identifiers;
* a `COMPLETED` run holds no failed stage.

**`ExecutionEvent`** — a closed union of six frozen events, each carrying
`sequence`, `run_id`, `simulation_date`. `in_sequence(events)` verifies ordering.

**`Progress`** — `(completed_stages, total_stages, completed_ticks, total_ticks)`.
Percentages are `float | None`: an open-ended period has no denominator, and a
fabricated one would be worse than none.

**Not implemented in EDS v1.0.** No event bus — these are values.

---

## `eds.platform.scheduler`

**Purpose.** Execute a run. The only module in the platform that does anything
(PADR-013).

**Depends on.** `eds.platform.{run,runtime,time,execution}`.
**Used by.** Callers, directly.

### Public API

`execute`, `StageExecutor`, `StageRequest`, `StageOutput`, `StageExecutionError`,
`ExecutionReport`

### The seam

```python
@dataclass(frozen=True, slots=True)
class StageRequest:
    stage: PlannedStage
    simulation_date: date
    run_id: str
    project_id: str
    seed: int | None
    data_directory: Path


@dataclass(frozen=True, slots=True)
class StageOutput:
    rows_by_dataset: dict[str, int]
    warnings: tuple[ExecutionWarning, ...] = ()


@runtime_checkable
class StageExecutor(Protocol):
    def execute(self, request: StageRequest) -> StageOutput: ...
```

**`StageExecutionError(message, failure_type=GENERATION, cause=None)`** — how an
executor reports a classified failure.

### `execute(run, executor)`

Returns an `ExecutionReport(result, events, progress)` with a `succeeded`
property. **Never raises for a failed run** — a failure is an outcome, and making
callers handle both an exception and a status would mean two ways to ask one
question.

### Constraints on this module

The scheduler may not import `polars`, `eds.domains`, `eds.adapters`,
`threading`, `asyncio` or `logging`, and may make no wall-clock call. A test
asserts it stays under 220 AST statements — a guard on the claim that
coordination is all it does.

**Not implemented in EDS v1.0.** Retries, recovery, rollback, restart,
parallelism.

**Extension points.** `StageExecutor` is how any domain is run.

---

## `eds.domains.retail`

**Purpose.** The Retail business: entities, generators, rules, evolution.

**Depends on.** `eds.core`, `eds.platform.domain`, `eds.platform.config`.
**Used by.** `eds.runners.retail`, `eds.cli`.

### Public API

```python
from eds.domains.retail import RETAIL_DOMAIN_NAME, RetailDomain  # registers on import
```

Importing the package registers the domain. That is its one side effect, and it is
deliberately cheap: the descriptor defers every generator import until something
asks about a stage.

### Sub-packages

| Sub-package | Contents |
| --- | --- |
| `domain/` | Dataset declarations and enums, by area: `catalog`, `commerce`, `commercial`, `customer`, `geography`, `inventory`, `journey`, `supply_chain` |
| `generators/` | Business event generators, F001–F010 |
| `temporal/` | Evolution over simulated time — see below |
| `validation/` | Business rules, one module per feature |
| `config.py` | Every Retail settings model and loader |
| `registry.py` | `RetailDomain` |

### Stages

| Stage | Requires | Produces |
| --- | --- | --- |
| `master-data` | — | 14 datasets |
| `customers` | `countries`, `states`, `cities` | 4 datasets |
| `journey` | 7 datasets | 6 datasets |
| `commerce` | 8 datasets | 15 datasets |

Both `requires` and `produces` are **derived** from the same declarations the
generators use, so a description cannot drift from an implementation.

### Configuration

`SimulationConfig` aggregates fourteen models — see
[Architecture Reference §9](02_Architecture_Reference.md#9-configuration-model).
`load_config(config_dir)` loads all of them.

**Extension points.** Add a dataset by declaring it, collecting it, and assigning
a temporality — see [Maintainer Guide §4](03_Maintainer_Guide.md#4-how-to-add-a-dataset).

---

## `eds.domains.retail.temporal`

**Purpose.** What one simulated day does to the business (ADR-013, ADR-014).

**Depends on.** `eds.core`, Retail's schemas and generators.
**Used by.** `eds.runners.retail`.

**Imports nothing from** the platform's `run`, `scheduler`, `runtime`, `time` or
`project` — asserted by test.

### Public API

`BusinessContext`, `DayOfBusiness`, `advance_day`, `STAGE_DATASETS`,
`HISTORY_READ`, `RETAIL_STAGE_NAMES`, `Temporality`, `DATASET_TEMPORALITY`,
`temporality_of`, `validate_temporal_history`

### Important classes

**`BusinessContext`** — the entire hand-over from the platform:

```python
@dataclass(frozen=True, slots=True)
class BusinessContext:
    business_date: date
    seed: int

    def stream(self, name: str) -> int: ...  # seed for one named stream, this day
```

Two fields, asserted by test. No clock, no tick, no calendar, no run, no project.
`stream()` derives from `(seed, name, date)` — **by date, not by position**, which
is what makes a run divisible without changing its output.

**`DayOfBusiness`** — `(generated, persisted, settings, is_founding)`.
`generated` is what the day created (what a validator should see); `persisted` is
every dataset the stage changed as it now stands (what a writer should get).

**`advance_day(stage, config, context, upstream, history)`** — the domain's entry
point for running itself. **A stage founds itself the first time it runs:** a
stage whose own datasets are empty has no history to continue, so it builds one.
No tick counter, no first-run flag.

**`Temporality`** — `STATIC`, `APPEND_ONLY`, `MUTABLE_SNAPSHOT`,
`SLOWLY_CHANGING`. `temporality_of(name)` **raises** for an undeclared dataset
rather than defaulting.

**`HISTORY_READ`** — what each stage must be shown of the past. A stage always
reads its own datasets; two read further, because stock falls when things sell and
loyalty points are earned by spending. Neither is expressible as a plan
dependency.

### Internal modules

`context`, `temporality`, `datasets`, `identity`, `merge`, `rules`, `evolution`,
`day`. `identity` and `merge` are used through `day`; `rules` is used by the
runner.

---

## `eds.adapters`

**Purpose.** Where datasets are persisted and read back — the Store of Record
(PADR-003).

**Depends on.** `eds.core`, `polars`.
**Used by.** `eds.runners.retail`, `eds.cli`.

### Public API

| Module | Names |
| --- | --- |
| `eds.adapters.base` | `DatasetWriter`, `DatasetReader`, `WriteResult`, `AdapterError` |
| `eds.adapters.parquet.adapter` | `ParquetAdapter`, `PARQUET_ADAPTER_NAME` |

### Important interfaces

```python
@runtime_checkable
class DatasetWriter(Protocol):
    @property
    def name(self) -> str: ...
    def write(self, datasets: Mapping[str, pl.DataFrame]) -> tuple[WriteResult, ...]: ...


@runtime_checkable
class DatasetReader(Protocol):
    @property
    def name(self) -> str: ...
    def read(self, names: Iterable[str]) -> dict[str, pl.DataFrame]: ...
```

**`WriteResult`** — `(dataset, location, rows)`. `location` is deliberately a
string, not a `Path`: it is an identifier meaningful to the adapter — a file path,
a qualified table name, a topic.

**The destination is bound at construction**, not passed per call. A `Path` in the
signature would be a filesystem leaking into the contract; a SQL adapter has a
connection, Kafka has brokers, REST has a base URL, and none is a `Path`.

**`ParquetAdapter(directory)`** satisfies both protocols. Snappy-compressed
Parquet, one file per dataset, deterministic for the same input.

**Implementations must be deterministic**: writing the same frames twice produces
the same result. That is what lets determinism tests compare two runs byte for
byte.

**Extension points.** `DatasetWriter` / `DatasetReader` for a second target.

**Not implemented in EDS v1.0.** Any adapter other than Parquet.
`eds/exporters/{csv,delta,sql}` are placeholders.

---

## `eds.runners.retail`

**Purpose.** Teach the scheduler how to run Retail. The runtime integration
boundary (PADR-014, PADR-015).

**Depends on.** Everything: `eds.core`, `eds.platform`, `eds.domains.retail`,
`eds.adapters`.
**Used by.** Nothing. **Nothing may depend on it** — asserted by test.

### Public API

```python
from eds.runners.retail import RetailExecutor, RETAIL_STAGES, StageValidation, run_stage
```

Importing the package registers the Retail domain.

### Important classes

**`RetailExecutor(config=None, config_dir=None, reader=None, writer=None)`** —
satisfies `StageExecutor`. Per stage it does five things: read what the plan says
the stage requires; read what the stage has produced before; run the stage for the
request's date; write what changed; report row counts.

```python
executor = RetailExecutor()  # repository configs/
executor = RetailExecutor(config=my_config)  # explicit settings
executor = RetailExecutor(reader=fake, writer=fake)  # injected adapters
```

The **project's seed wins** over the configuration file's, because the project is
what makes a simulation reproducible. A project without a seed falls back to the
file.

**`RETAIL_STAGES`** — stage name → the function that validates that stage's day.
The keys are checked against the domain's declared stages by a test, so a stage
added without checks here fails loudly.

**`run_stage(stage, config, context, upstream, history)`** — generates (via the
domain), validates, and raises `StageExecutionError` with the `FailureType` that
names the failure.

### Failure classification

| Cause | Type |
| --- | --- |
| Unknown stage | `CONFIGURATION` |
| Upstream datasets unreadable | `DEPENDENCY` |
| Generator raised `KeyError` / `ValueError` | `GENERATION` |
| Validation found issues | `VALIDATION` |
| Write refused | `PERSISTENCE` |

Only this layer can tell these apart, which is why classification lives here.

### What it never does

Order stages, advance time, write state, emit events, build results, decide what a
business does, or open a file. Its whole surface is one method, and tests assert
the last two.

---

## `eds.cli`

**Purpose.** The `eds` command-line interface.

**Depends on.** `eds.core`, `eds.domains.retail`, `eds.adapters`.
**Used by.** Console script entry point `eds = "eds.cli.main:app"`.

### Public API

| Module | Names |
| --- | --- |
| `eds.cli.main` | `app`, `main`, `version` |
| `eds.cli.generate` | `generate_app`, `master_data` |

### Commands

`eds version` · `eds generate master-data` · `eds generate customers` ·
`eds generate journey` · `eds generate commerce`

Options and exit codes: [Handbook §11.1](01_Handbook.md#111-command-line--a-single-snapshot).

### Design note

The CLI **predates the platform and does not route through it**. It writes to
`PlatformConfig.output_directory` and knows nothing about projects, clocks or the
scheduler (PADR-005) — routing Retail through a registry it is the only member of
would have been change for its own sake.

**Not implemented in EDS v1.0.** A CLI for projects, multi-day runs, resuming, or
any domain other than Retail.

---

## Compatibility packages

Each re-exports its new home with explicit `X as X` bindings, so mypy sees the
names and the surface is auditable (PADR-005). A test asserts every name reached
through an old path is **the identical object**, not merely present.

| Old path | Now lives in |
| --- | --- |
| `eds.config` | `eds.core.config` + `eds.platform.config` + `eds.domains.retail.config` |
| `eds.domain.*` | `eds.domains.retail.domain.*` |
| `eds.generators.*` | `eds.domains.retail.generators.*` |
| `eds.validation.*` | `eds.domains.retail.validation.*` |
| `eds.exporters.parquet.*` | `eds.adapters.parquet.*` |

These are a deprecation layer, not a permanent fixture. **New code should import
from the owning package.**

---

## Reserved packages

Each contains only a docstring saying contents arrive in a later feature.
**Not implemented in EDS v1.0.** Do not import them; do not delete them.

| Package | Reserved for |
| --- | --- |
| `eds/events/` | Business event definitions that drive state changes |
| `eds/simulation/` | Simulation engines: scheduling, events, workflows, probability |
| `eds/state/` | Mutable simulation state containers |
| `eds/workflows/` | Multi-step business workflows composed from events |
| `eds/exporters/csv/` | CSV exporter |
| `eds/exporters/delta/` | Delta Lake exporter |
| `eds/exporters/sql/` | SQL exporter |
| `eds/platform/state.py` | Platform-level state |

---

## Package diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                              eds.core                                  │
│  schema (Dataset, ForeignKey) · frames · random_streams · config       │
│  validation/ (ValidationIssue, referential checks)                     │
│  ── imports nothing in eds but eds.version                             │
└──────┬─────────────────────┬─────────────────────┬────────────────────┘
       │                     │                     │
       ▼                     ▼                     ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  eds.platform    │  │  eds.domains     │  │  eds.adapters    │
│                  │  │    .retail       │  │                  │
│ metadata         │  │                  │  │ base             │
│ domain ◀─────────┼──┤ registry         │  │  DatasetWriter   │
│  SimulationDomain│  │ config           │  │  DatasetReader   │
│  DomainStage     │  │ domain/          │  │  WriteResult     │
│ config           │  │ generators/      │  │ parquet/         │
│  PlatformConfig  │◀─┤ temporal/        │  │  ParquetAdapter  │
│ execution/       │  │  BusinessContext │  │                  │
│  ExecutionPlan   │  │  advance_day     │  │ = Store of       │
│ project/         │  │  Temporality     │  │   Record         │
│  Project, State  │  │ validation/      │  │                  │
│ time/            │  │                  │  │                  │
│  SimulationClock │  │                  │  │                  │
│ run/             │  │                  │  │                  │
│  SimulationRun   │  │                  │  │                  │
│ runtime/         │  │                  │  │                  │
│  RunResult       │  │                  │  │                  │
│ scheduler/       │  │                  │  │                  │
│  execute()       │  │                  │  │                  │
│  StageExecutor   │  │                  │  │                  │
└────────▲─────────┘  └────────▲─────────┘  └────────▲─────────┘
         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               │
                  ┌────────────────────────┐
                  │  eds.runners.retail    │
                  │  RetailExecutor        │
                  │  run_stage             │
                  │  ── imports all three  │
                  │  ── nothing imports it │
                  └────────────────────────┘

                  ┌────────────────────────┐
                  │       eds.cli          │
                  │  eds generate …        │
                  │  ── core + domains +   │
                  │     adapters only      │
                  └────────────────────────┘
```
