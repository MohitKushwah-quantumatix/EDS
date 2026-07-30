# PADR-014: The Runner Is a Third Party to the Platform and the Domain

**Status:** Accepted (P006.1)

**Builds on:** PADR-002 (platform-independent domains), PADR-003 (adapter
isolation), PADR-006 (the domain protocol describes, it does not execute),
PADR-013 (the executor arrives as an argument).

**Promoted by:** [PADR-015](PADR-015-runtime-integration-boundary.md), which
turns the fifth location this record discovered into a standing boundary rule -
what may cross it, what it owns, and what it may never acquire. This record
remains the origin story and the Retail-specific detail.

## Context

Six phases built a platform on the claim that it could run a business domain
without knowing about one. P006.1 tests that claim by running Retail.

The claim held. **A complete Retail simulation — thirty-nine datasets, all four
stages — now executes through the platform and produces output byte-identical
to the CLI's**, and it required no change to any platform module, any Retail
module, any adapter or the CLI.

Where it had to go was the interesting question. The code that teaches the
scheduler how to run Retail cannot live in the platform, which may not import a
domain (PADR-002, PADR-013), and cannot live in the domain, which may not
import the platform. It has nowhere to live in the existing four layers.

## Decision

A fifth location: `eds/runners/`, one package per domain.

It is not a platform layer and not a domain layer. **It is the only place
allowed to import both**, and that is its entire definition. A test asserts it
in both directions: the runner imports Retail, the scheduler and the adapters;
nothing in `eds/platform/` or `eds/domains/` imports the runner.

| Concept | Owns |
| --- | --- |
| `RetailExecutor` | Read, dispatch, write, report row counts |
| `RETAIL_STAGES` | Which function runs which declared stage |
| `stages.py` functions | Generate and validate, per stage |

### The read list comes from the plan

`PlannedStage.requires` is what the executor passes to the adapter. It is
derived from the same `REQUIRED_*` constants the CLI computes its own read list
from, so the runner never restates which datasets a stage consumes.

This is the first code to benefit from P002 deriving the graph from data flow
rather than from a hand-written declaration, and a test asserts that what each
stage asks to read is exactly `stage.requires`. If a feature starts reading a
dataset it never declared, the plan changes, the read changes, and the run
fails — instead of the declaration quietly rotting.

### Failures are classified where the knowledge is

Only this layer can tell a generator that raised from data that failed
validation from a disk that would not accept a write. So it raises
`StageExecutionError` with the `FailureType` that names it — `GENERATION`,
`VALIDATION`, `PERSISTENCE`, `DEPENDENCY`, `CONFIGURATION` — and the scheduler
records what it is told. Every one of the five is reachable and four are tested
against real failures.

### The project's seed wins over the configuration file's

A project is what makes a simulation reproducible (PADR-009), so
`request.seed` overrides `simulation.yaml`. A project created without a seed
falls back to the file, which keeps a quick unseeded run usable.

### Adapters are used through their protocols

The executor holds a `DatasetReader` and a `DatasetWriter`, defaulting to a
`ParquetAdapter` on the project's data directory. Nothing in the runner opens a
file, and a test asserts that too — which is what makes the first non-Parquet
adapter a constructor argument rather than a rewrite.

## The main integration finding: two execution paths

Retail now has two ways to run — `eds generate` and the platform — and they
duplicate the generate/validate/write sequence.

**1. Existing design.** The CLI holds the sequence inline in four Typer
commands. `eds/runners/retail/stages.py` now holds it again.

**2. Problem.** Duplication. A future feature could be added to one path and not
the other, and the two would silently diverge.

**3. Alternatives.**
 - *(a)* Refactor the CLI to call the runner. One path, no duplication.
 - *(b)* Keep both, and prove they agree.
 - *(c)* Keep both, and accept the risk.

**4. Advantages.** *(a)* eliminates the duplication at the source. *(b)*
converts the risk into a test, and leaves the CLI's ~1,700 tests and its
byte-identical guarantee untouched.

**5. Disadvantages.** *(a)* rewrites the most heavily tested code in the
repository during a phase chartered to *prove* the architecture, not to change
it — and the CLI's guarantee is byte-identical output, which is exactly what a
rewrite puts at risk. *(b)* leaves real duplication in place. *(c)* is not a
choice, it is a decision not to make one.

**6. Migration impact.** *(a)* touches every CLI command and its tests. *(b)*
touches nothing.

**7. Recommendation.** **(b) now, (a) next.** A test runs all four stages twice
— once through `eds generate`, once through the platform — and compares all
thirty-nine Parquet files byte for byte. Two paths that are *proven* to agree
are a cost; two that are *assumed* to agree are a defect. Once the platform
path has run in anger, the CLI should become a thin caller of the runner, and
that equivalence test is what will make the change safe.

## Platform deficiencies found

Neither was silently fixed.

### 1. Retail is not time-aware

The platform supplies a simulated date to every stage. Retail ignores it: every
timestamp is derived from a parent record and from `reference_date` in Retail's
own configuration, so the tick's date never reaches a generator.

The consequence is that **a multi-tick Retail run regenerates identical data on
every tick and overwrites itself**. A test asserts the current behaviour — two
runs on different simulated days produce identical bytes — precisely so it
fails when Retail becomes time-aware.

This is a *domain* gap, not a platform one, and it should not be closed by
having the runner overwrite `reference_date` with the tick's date: that would
change Retail's output and break the byte-identical guarantee this phase exists
to establish. It belongs in a Retail feature chartered to make the domain
time-aware, with the growth engine as its first real consumer.

### 2. Stage granularity is now visible, not theoretical

The plan sees Retail as four stages because that is what the CLI executes.
`commerce` is seven features with genuine dependencies between them, invisible
to the planner, so a scheduler cannot resume part-way through commerce or run
payments without regenerating orders. Executing for real makes the cost
concrete: a failure in reviews discards the whole commerce stage's work.

Splitting it is a *Retail* change (its registry declares the stages), not a
platform one. The platform is already able to plan seven nodes; nothing needs
to change here to allow it.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| **Put the executor in `eds/platform/`** | The platform would import Retail. This is the thing the platform exists not to do. |
| **Put the executor in `eds/domains/retail/`** | The domain would import the platform, breaking PADR-002 and making Retail unusable without the scheduler. |
| **Restore `SimulationDomain.execute()`** | Changes a frozen module and reopens a question P001.1 closed with evidence. It would also put orchestration back inside the domain. |
| **Have the runner call the CLI commands** | Typer commands exit processes and print; a scheduler needs values. |
| **Make the runner hold its own configuration file** | Retail's settings already live in `configs/`; a second source would be a second thing to keep in step. |
| **Overwrite `reference_date` with the tick's date** | Would change Retail's output and break the equivalence this phase establishes. |
| **A `RunnerRegistry` mirroring the domain registry** | Speculative. There is one runner. A registry becomes worth it when something has to *find* a runner by name, which nothing does. |

## Consequences

**Good.** The platform's central claim is now tested rather than argued. Retail
runs end to end through `SimulationRun → Scheduler → RetailExecutor → domain →
adapter → project → contracts`, and no platform component knows Retail exists.

**Good.** Every phase's abstraction earned its place under real load. The plan
supplied the read list, the clock supplied the date, the project supplied the
seed and took the state, the contracts described the outcome, and the scheduler
needed no special case for any of it.

**Good.** Resumption works on real data: a run halted after `customers`, then
resumed, produces bytes identical to an uninterrupted run. That is the
persistence design (PADR-009, PADR-013) proved rather than asserted.

**Cost.** The generate/validate/write sequence exists twice (above).

**Cost.** Adding a domain now means adding a runner as well as a domain — a
fifth thing to write. That is the honest price of forbidding the platform and
the domain from knowing about each other, and it is one package.

**Limitation.** The CLI still writes to `PlatformConfig.output_directory` and
knows nothing about projects or workspaces. Wiring it would change CLI
behaviour, which remains out of scope.

**Limitation.** A multi-tick Retail run is not yet meaningful (finding 1).

## Future integration

**A second domain.** Healthcare means `eds/domains/healthcare/` plus
`eds/runners/healthcare/`, and nothing else. The platform claim will be fully
tested when that is done and no platform file changes.

**The CLI.** Once the platform path has run in anger, `eds generate <stage>`
becomes a thin caller: open or create a project, build a one-tick run, execute
it with a `RetailExecutor`. The equivalence test is what will make that change
safe, and it is why it was written now.

**Growth (P007).** Has everything it needs from this layer: `RunResult.rows_by_dataset`
says how much an enterprise grew, `state.last_identifiers` says where numbering
stopped. It will, however, want finding 1 closed — a growth curve over ticks
that all generate the same data is not a growth curve.

## What this decision does not permit

A runner must not acquire platform responsibilities. It does not order stages,
advance time, write state, emit events or build results — a test asserts it
opens no files, and the executor's whole surface is one method. If a runner
starts needing to orchestrate, the need belongs in the scheduler; if it starts
needing to describe, the need belongs in the domain.
