# Enterprise Data Simulator — Maintainer Guide

**EDS v1.0 · Official documentation · Document 3 of 5**

Audience: senior engineers maintaining EDS. Purpose: how to evolve it safely.

Companion documents: [Handbook](01_Handbook.md) ·
[Architecture Reference](02_Architecture_Reference.md) ·
[Package Reference](04_Package_Reference.md) ·
[Developer Quick Start](05_Developer_Quick_Start.md) ·
[Documentation index](README.md)

---

## Table of contents

1. [Repository organisation](#1-repository-organisation)
2. [Architectural boundaries](#2-architectural-boundaries)
3. [How to add a domain](#3-how-to-add-a-domain)
4. [How to add a dataset](#4-how-to-add-a-dataset)
5. [How to add configuration](#5-how-to-add-configuration)
6. [How to extend simulation](#6-how-to-extend-simulation)
7. [How to preserve backward compatibility](#7-how-to-preserve-backward-compatibility)
8. [Testing strategy](#8-testing-strategy)
9. [Performance expectations](#9-performance-expectations)
10. [Coding conventions](#10-coding-conventions)
11. [Review checklist](#11-review-checklist)
12. [Release checklist](#12-release-checklist)
13. [Versioning policy](#13-versioning-policy)
14. [Common mistakes](#14-common-mistakes)
15. [Refactoring guidelines](#15-refactoring-guidelines)
16. [When a PADR is required](#16-when-a-padr-is-required)

---

## 1. Repository organisation

| Path | Contains | Change frequency |
| --- | --- | --- |
| `eds/core/` | Shared vocabulary. No business, no storage | Rarely — a change here affects everything |
| `eds/platform/` | Simulation lifecycle | Only for a new lifecycle capability |
| `eds/domains/retail/` | The Retail business | Whenever Retail changes |
| `eds/adapters/` | Parquet read/write — the Store of Record | Rarely |
| `eds/runners/retail/` | Retail wired into the platform | When the seam changes |
| `eds/cli/` | The `eds` command | Rarely; it predates the platform |
| `eds/tests/` | 2,414 tests, one module per subject | Every change |
| `configs/` | One YAML file per feature | Whenever a setting is added |
| `docs/platform/` | PADRs, vision, layer architecture, roadmap | With every architectural decision |
| `docs/architecture/` | Retail ADRs | With every business rule decision |
| `docs/features/` | Per-feature context, prompt, review | With every feature |

### Placeholder packages

Each contains only a docstring. They mark where future work belongs so that it is
not bolted onto something else.

`eds/events/`, `eds/simulation/`, `eds/state/`, `eds/workflows/`,
`eds/exporters/csv/`, `eds/exporters/delta/`, `eds/exporters/sql/`,
`eds/platform/state.py`.

**Not implemented in EDS v1.0.** Do not import them and do not delete them.

### Compatibility shims

`eds/config.py`, `eds/domain/`, `eds/generators/`, `eds/validation/`,
`eds/exporters/` re-export their new homes. See [§7](#7-how-to-preserve-backward-compatibility).

---

## 2. Architectural boundaries

The four rules that must never be broken, and the test that catches each.

| Rule | Test |
| --- | --- |
| `eds.platform` imports no domain and no runner | `test_the_platform_does_not_know_retail_exists` |
| `eds.domains` imports no runner | `test_the_retail_domain_does_not_know_the_runner_exists` |
| `eds.domains` imports none of the platform's `run`, `scheduler`, `runtime`, `time`, `project` | `test_retail_never_learns_what_ran_it` |
| `eds.core` imports nothing in `eds` except `eds.version` | package-layout tests |

A domain *may* import `eds.platform.domain` and `eds.platform.config` — the
protocol it satisfies and the run-level settings model. Both are declarations.

### Where does my code belong?

```
Does it need BOTH platform and domain vocabulary?
├── YES ──▶ eds/runners/<domain>/
│           But first: does it really? See the note below.
└── NO
    ├── Is it about a business?              ──▶ eds/domains/<domain>/
    ├── Is it about running a simulation?    ──▶ eds/platform/
    ├── Is it about where data is persisted? ──▶ eds/adapters/
    └── Is it true regardless of both?       ──▶ eds/core/
```

**The note.** Work "needing both" is usually work that has not been decomposed
yet. Generation lived in the runner for one phase because the domain had no entry
point for being run; once it had one, generation moved. PADR-015 states the
invariant: business rules accumulating in the runner means responsibilities have
leaked from the domain; orchestration accumulating means they have leaked from the
platform. **Growth of the runner is a review trigger, not normal evolution.**

### Forbidden techniques

* **Reflection, dynamic imports, string-based module lookup.** Every boundary test
  works by reading imports; a rule enforced that way is only worth having while
  imports are what the code uses (PADR-015).
* **Wall-clock calls in generation.** `datetime.now`, `date.today`, `time.time`,
  `utcnow`. Determinism depends on their absence and tests assert it.
* **Unseeded randomness.** Every random value comes from
  `eds.core.random_streams`.

---

## 3. How to add a domain

The platform's central claim. If this requires editing a platform file, the claim
was wrong and the change should stop.

### What to create

```
eds/domains/<name>/
├── __init__.py          Imports the registry module — registration is the one side effect
├── registry.py          The concrete SimulationDomain
├── config.py            Settings models and loaders
├── domain/              Dataset declarations and enums
├── generators/          Business event generators
├── temporal/            What one simulated day does (if the domain is time-aware)
└── validation/          Business rules

eds/runners/<name>/
├── __init__.py          Imports the domain (registering it); exports the executor
├── executor.py          A StageExecutor
└── stages.py            Runs a stage for a date; classifies failures

configs/                 One YAML file per feature
```

### The describe-only contract

`registry.py` implements `SimulationDomain`:

```python
class MyDomain:
    @property
    def name(self) -> str: ...
    @property
    def stages(self) -> tuple[DomainStage, ...]: ...
    @property
    def dataset_names(self) -> tuple[str, ...]: ...


register_domain(MyDomain())
```

Four rules learned from Retail:

1. **Derive, never restate.** Build `DomainStage.produces` from the same schema
   declarations the generators use, and `requires` from the same `REQUIRED_*`
   constants. A description that can drift from the implementation will.
2. **Defer generator imports into the properties.** `import eds.domains.<name>`
   must stay cheap — merely *knowing a domain exists* should not cost as much as
   running it.
3. **Subtract what you produce.** A stage running several features requires the
   union of their inputs *minus* what it produces along the way. Otherwise the
   plan sees a cycle.
4. **A domain must be closed.** Every requirement must be produced by some stage.
   Externally supplied inputs are not expressible — **not implemented in EDS
   v1.0.**

### The runner

`executor.py` satisfies `StageExecutor`: read `stage.requires`, read the domain's
declared history, build the domain's own context value, invoke the domain, write
what changed, report row counts. Classify every failure with the `FailureType`
that names it.

### Verification

| Check | Expectation |
| --- | --- |
| `plan_domain("<name>")` | Returns an ordered plan with no manual intervention |
| Boundary tests | Pass unchanged |
| Platform files changed | **Zero** |
| A full run | `execute(create_run(project, clock), MyExecutor())` completes |

---

## 4. How to add a dataset

### 1. Declare it

```python
# eds/domains/<name>/domain/<area>/schema.py
MY_DATASET = Dataset(
    name="my_dataset",
    columns={"my_id": pl.Int64(), "customer_id": pl.Int64(), "created_at": pl.Datetime("us")},
    primary_key="my_id",
    unique_columns=("some_code",),
    foreign_keys=(ForeignKey("customer_id", "customers", "customer_id"),),
)
```

Everything downstream reads this declaration: validation, renumbering, and — in a
time-aware domain — merging. **Per-column nullability is not expressible in
`Dataset`. Not implemented in EDS v1.0.**

### 2. Add it to the area's collection

So `dataset_names()` includes it and the domain's description picks it up
automatically.

### 3. Declare its temporality — mandatory for a time-aware domain

```python
# eds/domains/<name>/temporal/temporality.py
DATASET_TEMPORALITY = {
    ...,
    "my_dataset": Temporality.APPEND_ONLY,
}
```

A dataset with no declared temporality **raises** rather than defaulting. This is
deliberate: silently appending to something that should have been replaced
corrupts a history quietly. A test asserts the classification covers exactly the
datasets the domain declares, so this step cannot be skipped.

Choosing:

| Question | Answer |
| --- | --- |
| Is every row a record of something that happened? | `APPEND_ONLY` |
| Is it a picture of *now*, replaced when it changes? | `MUTABLE_SNAPSHOT` |
| One row per subject, with a few attributes that move? | `SLOWLY_CHANGING` |
| Written on the founding day and never again? | `STATIC` |

### 4. Generate it, validate it, test it

The generator returns a frame built with `build_frame(MY_DATASET, {...})`, which
enforces the declared schema. The validator checks what only this dataset's rules
can check; keys and foreign keys are already covered by the shared framework.

### 5. Consequences to expect

* The domain's `dataset_names` grows, so the plan and any dataset-count test
  change. Update the counts rather than loosening the assertions.
* If the dataset has a business code derived from its identifier, or a code that
  counts within a day, a time-aware domain must restate it after renumbering.
* Determinism digests change. Re-baseline deliberately and say so in review.

---

## 5. How to add configuration

### A setting on an existing feature

```python
# eds/domains/<name>/config.py
class ReviewConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    my_setting: int = Field(default=5, ge=0, le=100)
```

Then add it to the YAML file **with a comment saying what it means**, and to the
docstring's `Attributes:` block. Add a test for the boundary values, not just the
default.

### A whole new feature's settings

1. A new model in `config.py`, frozen, `extra="forbid"`.
2. A `<FEATURE>_CONFIG_FILE` constant.
3. A `load_<feature>_config(config_dir)` function.
4. A field on `SimulationConfig`, and a line in `load_config`.
5. Both names added to `__all__` — and to `eds/config.py` for compatibility.
6. `configs/<feature>.yaml`, commented.

### Required or optional?

**Default to required**, matching the other twelve loaders: a missing file that
the generators need should fail at load with a precise error.

**Make it optional only when the capability itself is optional.** `evolution.yaml`
is the single precedent: it describes how a day changes an enterprise, and a
configuration directory written before the domain could evolve has no opinion
about that. Its loader checks for the file and returns defaults. If you add an
optional loader, document the reason in its docstring — the asymmetry needs
justifying every time.

### Rules

* Platform settings go in `PlatformConfig`; business settings go in the domain
  (PADR-007). A setting that is neither is probably two settings.
* Never read a YAML file outside a loader.
* Never mutate a config model. Use `model_copy(update={...})`.

---

## 6. How to extend simulation

### Adding a business rule

Belongs in the domain's `validation/` package, as a function returning
`list[ValidationIssue]`. Rules that hold across a *whole history* rather than
within one unit of work belong in the temporal rules, not the feature validators —
the two are checked at different scopes for good reason.

### Making a domain time-aware

Retail's `temporal/` package is the reference implementation. The obligations
(PADR-016, ADR-013) are short:

1. **Derive state from persisted data.** No flag, no counter, no checkpoint.
2. **Absence of data means founding.** A stage whose own datasets are empty builds
   a history; one that has history continues it.
3. **Seed by business date, not position.** `stream_seed(seed, f"{stream}@{date}")`.
   A tick index would make output depend on how a run reached a date, which breaks
   division, retry and resume.
4. **Never rewrite history.** One merge rule per temporality, and nowhere else.
5. **Continue identifiers**, and restate any code derived from one.

The property to test is unusual and worth copying: **run N days at once and the
same N days in several pieces, and compare bytes.** If they differ, something
depends on the run's shape.

### Adding a stop condition

`eds.platform.run.stop` holds a closed union. Adding a kind means: the new frozen
class, the union, `STOP_CONDITION_KINDS`, document round-tripping, and the
`match` in the scheduler's `_reached_stop`. The union is closed precisely so the
compiler and the tests find every site.

### Adding a tick unit

`TickUnit` in `eds.platform.time.tick`, plus advancement and elapsed-count
handling. Note the lesson of PADR-010: advancement is anchored to the period's
start because month ticks are not associative under day-of-month clamping. A new
unit with irregular length needs the same treatment and a test that steps and
jumps agree.

### Not implemented in EDS v1.0

Growth engine · snapshots · SCD/CDC · parallel execution · retries, recovery,
rollback, restart · delivery to databases or APIs · a CLI for multi-day runs ·
run history persistence · externally supplied domain inputs.

Design documentation exists for delivery
([P007B](platform/P007B-destination-adapter-framework.md),
[PADR-017](platform/PADR-017-enterprise-distribution-architecture.md)). The rest
have homes reserved and nothing written.

---

## 7. How to preserve backward compatibility

PADR-005 makes a specific, measurable claim: the four commands at seed 42 produce
39 Parquet files whose SHA-256 digests are identical, file for file, to those
produced before the platform refactor.

**That claim still holds and must keep holding.**

### The determinism check

Regenerate all four stages into a scratch directory and compare per-file SHA-256
digests against a known baseline. Any difference is either a bug or a deliberate
change that must be stated in review. The repository's own verification runs this
on every phase.

### What must not change without a decision

| Guarantee | Consequence of breaking it |
| --- | --- |
| Byte-identical CLI output at seed 42 | Every downstream consumer's fixtures break |
| Pre-platform import paths resolve to the identical objects | External code breaks |
| The founding day of a time-aware run equals the CLI snapshot | Two paths diverge silently |
| Existing rows of an append-only dataset | A history stops being a history |

### Rules for compatibility shims

Explicit `X as X` re-exports, never `import *`, so mypy sees the names and the
surface is auditable. A test asserts every name reached through an old path is
*the identical object*, not merely present.

### Adding an optional file

New configuration must default rather than fail, or an existing configuration
directory stops loading. This is the same argument in a new place.

---

## 8. Testing strategy

### The four gates

| Gate | Command | Must be |
| --- | --- | --- |
| Tests | `pytest` | 2,413 passed, 1 deselected |
| Lint | `ruff check .` | All checks passed |
| Format | `ruff format --check .` | All files formatted |
| Types | `mypy eds` | No issues in 365 source files |

All four must pass before a change is complete. Reference timing: the default
suite is about eight minutes.

### Test organisation

One module per subject, named for what it tests. Test *names are sentences* about
behaviour, and the docstring says why the behaviour matters:

```python
def test_a_payment_cannot_settle_an_order_that_was_never_placed() -> None:
    """It takes two days to break this; one day's output cannot."""
```

### Kinds of test, and what each is for

| Kind | Asserts | Example |
| --- | --- | --- |
| Unit | One function's behaviour | A merge rule keeps history first |
| Schema | Declared columns, types, keys | Every dataset's primary key is unique |
| Business rule | A domain invariant | No review precedes its delivery |
| Architecture | Import boundaries, by AST | The platform does not import a domain |
| Determinism | Byte-identical output | Two runs of one project produce identical files |
| Equivalence | Two paths agree | The platform path matches the CLI, all 39 files |
| Contract | A protocol is satisfied | `isinstance(executor, StageExecutor)` |
| End-to-end | A whole run | A year of trading holds together |

The **architecture tests** are the load-bearing ones. They are what make the
layering a property rather than an aspiration, and they must never be weakened to
accommodate a change — a failing boundary test means the change is in the wrong
package.

### The `slow` marker

```bash
pytest              # excludes slow tests (addopts has -m "not slow")
pytest -m slow      # runs only them
```

Reserved for simulations whose *length* is the point and which assert nothing a
shorter run does not. There is one: a 365-day simulation, about six minutes. The
default suite runs 120 days instead.

Do not mark a test `slow` because it is inconvenient. Mark it slow when a shorter
version gives the same assurance.

### What a new feature owes

* Unit tests for each new function, including boundary values.
* A schema test if it declares a dataset.
* A business-rule test for each rule it introduces.
* A determinism test if it generates anything.
* A temporality declaration and its test if the domain is time-aware.

---

## 9. Performance expectations

Measured on a development laptop at default scale (1,000 customers, 1,000
products).

| Operation | Time | Output |
| --- | --- | --- |
| `eds generate master-data` | 0.4 s | 14 datasets |
| `eds generate customers` | 0.9 s | 4 datasets |
| `eds generate journey` | 3.3 s | 6 datasets |
| `eds generate commerce` | 1.1 s | 15 datasets |
| **All four** | **5.7 s** | **39 files, 4.1 MB, 152,890 rows** |
| Default test suite | ~8 min | — |
| `pytest -m slow` (365 days) | ~6 min | — |

### Cost model

* **`journey` dominates** a snapshot: `product_views` is the finest-grained event
  at 88,248 rows, and journey volume scales with customer count.
* **Datasets are built in memory** before being written. Memory, not CPU, is the
  practical ceiling on scale.
* **A multi-day run costs more per day than a snapshot costs in total**, because
  validation runs over the accumulated history on every stage of every day. Some
  rules are about a *date* rather than a row and cannot be narrowed to one day's
  output.
* **Sequential by design.** Parallelism is not implemented in EDS v1.0.

### When adding something expensive

State the cost in review with a measurement. If a check can be expressed over one
unit of work instead of a whole history, express it that way. If it cannot, say
why — that is a real constraint, not a failure.

---

## 10. Coding conventions

Enforced by `ruff.toml`, `pyproject.toml` (mypy) and review.

### Mechanical

| Rule | Value |
| --- | --- |
| Line length | 100 |
| Quotes | Double |
| Target version | py312 |
| Docstring convention | Google, enforced by `pydocstyle` (`D`) |
| Import order | isort, `eds` as first-party |
| Type annotations | Required on every function (`disallow_untyped_defs`) |
| `from __future__ import annotations` | At the top of every module |

Ruff rule families selected: `A`, `ARG`, `B`, `C4`, `D`, `E`, `F`, `I`, `N`,
`PTH`, `RET`, `SIM`, `UP`, `W`.

### Idioms used throughout

| Idiom | Use |
| --- | --- |
| `@dataclass(frozen=True, slots=True)` | Every value object |
| `__post_init__` raising a `ValueError` subclass | Validation at construction |
| `Protocol` with `@runtime_checkable` | Extension points |
| `type X = A \| B \| C` | A closed union where a consumer must handle every kind |
| `StrEnum` | Every enumeration that appears in data or documents |
| `Final` | Module-level constants |
| `Mapping` in, `dict` out | Function signatures |
| `model_copy(update={...})` | Deriving configuration; never mutate |

### Docstrings

Every module, class and function. Module docstrings explain *why* the module
exists, not what its functions are called. Function docstrings use `Args:`,
`Returns:`, `Raises:`.

The house style is to record the *reason* alongside the rule, and to keep it
where the code is:

```python
def _persist(...) -> None:
    """Record progress, after a stage succeeded and never before.

    Persisting only completed work is what makes a failed run resumable rather
    than ambiguous. If a partially-run stage were recorded, a resume would skip
    work that was never finished and the datasets would be silently short.
    """
```

A comment explaining a non-obvious decision is expected. A comment restating the
code is noise.

---

## 11. Review checklist

### Boundaries

- [ ] No new import crosses a forbidden boundary; the architecture tests pass
      unmodified
- [ ] Nothing new landed in `eds/runners/` that needs only one vocabulary
- [ ] No reflection, dynamic import or string-based module lookup
- [ ] No wall-clock call in generation

### Correctness

- [ ] All four gates pass
- [ ] Determinism verified — digests unchanged, or the change is stated and
      justified
- [ ] New dataset: declared, collected, temporality assigned, validated, tested
- [ ] New configuration: frozen model, `extra="forbid"`, YAML comment, docstring,
      boundary test
- [ ] Failures classified with the `FailureType` that names them

### Design

- [ ] No abstraction introduced without demonstrated duplication
- [ ] No speculative parameter, hook or registry
- [ ] Derived rather than restated: no second list that can drift from the first
- [ ] A decision that constrains future work has a PADR or ADR ([§16](#16-when-a-padr-is-required))

### Documentation

- [ ] Docstrings say *why*
- [ ] A flaw found in a frozen module is **documented, not silently changed**
- [ ] Affected documents updated: the five suite documents, the PADR/ADR indexes,
      the roadmap
- [ ] Anything unimplemented is marked "Not implemented in EDS v1.0"

---

## 12. Release checklist

- [ ] All four gates green on a clean checkout
- [ ] `pytest -m slow` green
- [ ] Determinism verified against the baseline digests
- [ ] `eds/version.py` bumped — this is the single source; the build backend reads
      it, so the distribution and runtime versions cannot drift
- [ ] `PLATFORM_CONTRACT_VERSION` bumped **if** the domain or adapter protocol
      changed
- [ ] `MANIFEST_VERSION` / `STATE_VERSION` bumped **if** a document shape changed,
      with a supported-version check
- [ ] Documentation suite reviewed for statements the release makes untrue
- [ ] PADR/ADR indexes match the files present
- [ ] `pip install -e ".[dev]"` from clean, then `eds version`
- [ ] The four CLI commands run from clean and produce 39 files

### Not present in the repository

No CI configuration, no `CONTRIBUTING.md`, no `CHANGELOG.md`, no pre-commit
configuration, no `Makefile`. **The gates are run by hand.** If continuous
integration is added, it should run exactly the four gates plus the determinism
check.

---

## 13. Versioning policy

Three versions, deliberately independent.

| Version | Where | Meaning | Bump when |
| --- | --- | --- | --- |
| `__version__` | `eds/version.py` | The distribution | Any release |
| `PLATFORM_CONTRACT_VERSION` | `eds.platform.metadata` | The domain and adapter protocols | A protocol changes shape |
| `MANIFEST_VERSION`, `STATE_VERSION` | `eds.platform.project` | Persisted document shapes | A document gains, loses or redefines a field |

`eds/version.py` is public API — `from eds.version import __version__` — and the
build backend reads it, so there is exactly one place to change.

Document versions matter because a project on disk outlives the code that wrote
it. A version bump must come with a supported-version check that gives a precise
error rather than a confusing failure.

`0.1.0` today; **v1.0 refers to the frozen architecture, not the distribution
version.**

---

## 14. Common mistakes

**Putting business logic in the runner.** It compiles, the tests pass, and the
boundary has been lost. PADR-015's invariant is the check: if it is a rule about a
business, it belongs in the domain.

**Adding a dataset without a temporality.** It raises at merge time rather than at
declaration time, and only on the second simulated day.

**Restating instead of deriving.** A second list of dataset names, required
inputs or stage names will drift. Read the declaration.

**Seeding from a position.** A tick index, an attempt number, a stage ordinal —
any of them makes output depend on how a run reached a moment, and breaks
division and resume. Seed from the business date (PADR-016).

**Trusting a derived value over the data.** A cache is fine; a cache that must be
believed because the history can no longer produce it is a second source of truth.

**Weakening an architecture test.** A failing boundary test is information: the
change is in the wrong package.

**Adding an abstraction for the second case.** Generalise from two working
implementations, never from one and a prediction.

**Silently fixing a flaw in a frozen module.** Document it as an architectural
challenge. The repository's history is largely a record of doing this, and it is
why the design is traceable.

**Mutating a configuration model.** They are frozen. Use `model_copy`.

**Assuming the CLI and the platform path are the same code.** They are two paths
proven equivalent by a byte-identity test. Change one and check the other.

---

## 15. Refactoring guidelines

### Safe by construction

* Renaming a private function.
* Extracting a helper within a module.
* Adding a test.
* Improving a docstring.
* Adding an optional parameter with a default that preserves behaviour.

### Requires the determinism check

Anything touching a generator, a schema, a seed, an ordering or a merge. Run the
digest comparison before and after; an unexplained difference is a bug.

### Requires a decision record

Anything changing a boundary, a protocol, a persisted document shape, or a rule
another module relies on. See [§16](#16-when-a-padr-is-required).

### Sequencing a risky refactor

The pattern the repository uses, and it works:

1. **Add the new thing, unused.** Nothing calls it. Gates stay green.
2. **Switch one caller.** Prove equivalence — byte-identical output is the
   strongest available proof and it already has a harness.
3. **Switch the rest.**
4. **Remove the old thing** only when nothing references it.

Each step is independently reviewable and independently revertible.

### Two paths, temporarily

Sometimes the honest answer is to keep both and prove they agree, rather than
rewrite heavily tested code during a phase chartered to do something else. Two
paths *proven* to agree are a cost; two *assumed* to agree are a defect. If you
take this route, write the equivalence test first — it is what makes the eventual
unification safe.

### When not to refactor

If the only justification is that the code would be tidier, and the code is
frozen, covered and correct — do not. ADR-006 freezes completed features
deliberately.

---

## 16. When a PADR is required

A **PADR** records a decision about the *platform*: where code may live, what may
depend on what, what a protocol is. An **ADR** records a decision about a
*domain's business rules*.

### A PADR is required when a change

- [ ] alters a dependency rule between packages
- [ ] adds or changes an extension point (a protocol, a registry, a factory)
- [ ] changes what a layer owns or is forbidden from owning
- [ ] changes a persisted document's shape or a contract version
- [ ] introduces a new package at the top level of `eds/`
- [ ] constrains what a future domain may do
- [ ] rejects an obvious design in favour of a less obvious one

### An ADR is required when a change

- [ ] introduces or changes a business rule that other features rely on
- [ ] changes how a business entity relates to another
- [ ] changes what makes generated data valid
- [ ] changes how a domain behaves over time

### A record is *not* required for

Adding a setting; adding a dataset within an existing pattern; a bug fix that
restores intended behaviour; a test; a performance improvement with no observable
change.

### Format

Follow the neighbouring records. Both indexes are tables and must be updated:
[`docs/platform/README.md`](platform/README.md) and
[`docs/architecture/README.md`](architecture/README.md).

Every record states: the problem, the decision, the alternatives considered *and
why each was rejected*, the consequences including the costs, and what the
decision does not permit. The last two are what make a record useful five years
later.

### Write it when the decision is taken

Not before — a record written before acceptance describes a decision nobody has
made. Not long after — the alternatives are the first thing forgotten, and they
are the most valuable part.
