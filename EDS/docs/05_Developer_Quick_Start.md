# Enterprise Data Simulator — Developer Quick Start

**EDS v1.0 · Official documentation · Document 5 of 5**

Audience: a developer joining the project. Goal: productive in under 30 minutes.

Companion documents: [Handbook](01_Handbook.md) ·
[Architecture Reference](02_Architecture_Reference.md) ·
[Maintainer Guide](03_Maintainer_Guide.md) ·
[Package Reference](04_Package_Reference.md) ·
[Documentation index](README.md)

---

## Table of contents

1. [Before you start](#1-before-you-start)
2. [Clone and install — 5 minutes](#2-clone-and-install--5-minutes)
3. [Run your first simulation — 1 minute](#3-run-your-first-simulation--1-minute)
4. [Understand the output — 5 minutes](#4-understand-the-output--5-minutes)
5. [Run a multi-day simulation — 3 minutes](#5-run-a-multi-day-simulation--3-minutes)
6. [Run the tests — 10 minutes](#6-run-the-tests--10-minutes)
7. [Useful commands](#7-useful-commands)
8. [Repository tour — 5 minutes](#8-repository-tour--5-minutes)
9. [Debugging tips](#9-debugging-tips)
10. [Contribution workflow](#10-contribution-workflow)
11. [A first change to try](#11-a-first-change-to-try)
12. [Checklist](#12-checklist)

---

## 1. Before you start

| Need | Value |
| --- | --- |
| Python | 3.12 or later. 3.13 is what the suite runs on |
| Disk | ~10 MB |
| Network | None after install |
| Database | None |

Check your interpreter:

```bash
python --version        # Python 3.12.x or later
```

---

## 2. Clone and install — 5 minutes

```bash
# From the repository root
python -m venv .venv

# Activate
source .venv/bin/activate          # macOS / Linux
.venv\Scripts\activate             # Windows PowerShell
source .venv/Scripts/activate      # Windows Git Bash

# Install the package and the development tools, editable
pip install -e ".[dev]"
```

Verify:

```bash
eds version
```

```
0.1.0
```

**If `eds` is not found**, the virtual environment is not active or `pip` used a
different interpreter. `python -m eds.cli.main version` works either way and
tells you whether the package itself imports.

---

## 3. Run your first simulation — 1 minute

Four commands, in order. Each reads what the previous one wrote.

```bash
eds generate master-data
eds generate customers
eds generate journey
eds generate commerce
```

Total: **about 6 seconds**, producing 39 Parquet files (~4 MB) in `output/`.

The last command prints:

```
Validation passed.
Seed: 42
Output: /path/to/output
  shopping_carts                    914 rows
  cart_items                      1,703 rows
  checkout                          376 rows
  orders                            311 rows
  order_lines                       513 rows
  order_status_history              879 rows
  payments                          309 rows
  payment_status_history            596 rows
  shipments                         283 rows
  shipment_items                    469 rows
  shipment_status_history         1,379 rows
  returns                            35 rows
  return_items                       42 rows
  return_status_history             168 rows
  reviews                            58 rows
Total: 8,035 rows across 15 datasets
```

**Order matters.** `customers` reads what `master-data` wrote. Out of order gives
exit code 2.

---

## 4. Understand the output — 5 minutes

```bash
ls output/ | head
python -c "import polars as pl; print(pl.read_parquet('output/orders.parquet').head())"
```

### The whole enterprise in one query

```python
import polars as pl

orders = pl.read_parquet("output/orders.parquet")
customers = pl.read_parquet("output/customers.parquet")
lines = pl.read_parquet("output/order_lines.parquet")
products = pl.read_parquet("output/products.parquet")

top = (
    lines.join(orders, on="order_id")
    .join(products, on="product_id")
    .join(customers, on="customer_id")
    .group_by("product_name")
    .agg(pl.col("line_total").sum().alias("revenue"))
    .sort("revenue", descending=True)
    .head(5)
)
print(top)
```

Every join resolves. There are no orphan keys — that is validated on every run,
not assumed.

### The chain

Each link narrows the one before it:

```
5,752 sessions ─▶ 914 carts ─▶ 376 checkouts ─▶ 311 orders
   ─▶ 309 payments ─▶ 283 shipments ─▶ 35 returns · 58 reviews
```

Every drop-off is a configurable business rate, not an accident. Full dataset
list and row counts: [Handbook §12.3](01_Handbook.md#123-row-counts-at-default-scale).

### Prove determinism to yourself

```bash
eds generate master-data --output run-a
eds generate master-data --output run-b
python -c "
import hashlib, pathlib
h = lambda d: {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(pathlib.Path(d).glob('*.parquet'))}
print('identical:', h('run-a') == h('run-b'))
"
```

```
identical: True
```

---

## 5. Run a multi-day simulation — 3 minutes

The CLI produces one snapshot. Simulating *time* — a business evolving over days —
is done through the Python API.

**A CLI for multi-day runs is not implemented in EDS v1.0.**

Save as `demo.py`:

```python
from datetime import date
from pathlib import Path

from eds.domains.retail.config import load_config
from eds.platform.project.project import create_project
from eds.platform.run.configuration import RunConfiguration
from eds.platform.run.run import create_run
from eds.platform.run.stop import AfterTicks
from eds.platform.scheduler.scheduler import execute
from eds.platform.time.clock import create_clock
from eds.runners.retail import RetailExecutor

# A small enterprise, so this finishes quickly
config = load_config()
small = config.model_copy(
    update={
        "customers": config.customers.model_copy(update={"customer_count": 20}),
        "master_data": config.master_data.model_copy(
            update={
                "product_count": 30,
                "brand_count": 3,
                "supplier_count": 2,
                "warehouse_count": 2,
                "warehouses_per_product": 1,
                "root_categories": 2,
                "children_per_category": 2,
            }
        ),
    }
)

project = create_project(Path("./my-shop"), name="Demo Shop", domain="retail", seed=42)
clock = create_clock(date(2026, 1, 1), end=date(2026, 1, 3))
run = create_run(project, clock, RunConfiguration(stop_condition=AfterTicks(3)))

report = execute(run, RetailExecutor(config=small))

print("status:", report.result.status)
print("ticks: ", report.progress.completed_ticks)
for stage in report.result.stages:
    print(
        " ",
        stage.stage_id,
        stage.status,
        stage.start_date,
        "->",
        stage.end_date,
        sum(stage.rows_by_dataset.values()),
        "rows",
    )
```

```bash
python demo.py
```

```
status: completed
ticks:  3
  retail:master-data completed 2026-01-01 -> 2026-01-03 490 rows
  retail:customers   completed 2026-01-01 -> 2026-01-03 329 rows
  retail:journey     completed 2026-01-01 -> 2026-01-03 5307 rows
  retail:commerce    completed 2026-01-01 -> 2026-01-03 552 rows
```

What you now have:

```
my-shop/
├── manifest.json     Identity: project_id, name, domain, seed, versions
├── state.json         current_date, completed_stages
└── data/              39 Parquet files — the Store of Record
```

**Day 1 founds** the enterprise. **Days 2 and 3 evolve** it: new customers
register, existing customers return, stock moves, loyalty accrues — and nothing
already written is rewritten.

```python
import polars as pl

c = pl.read_parquet("my-shop/data/customers.parquet")
print(c.group_by("registration_date").len().sort("registration_date").tail(4))
```

Customers registered on 2026-01-02 and 2026-01-03 are the ones the later days
added.

---

## 6. Run the tests — 10 minutes

```bash
pytest
```

```
2413 passed, 1 deselected in 487.01s (0:08:07)
```

The deselected test is a 365-day simulation marked `slow`. Run it if you want to:

```bash
pytest -m slow          # 1 passed in ~6 minutes
```

### Faster feedback while working

```bash
pytest eds/tests/test_orders.py              # one module
pytest -k "loyalty"                          # by name
pytest -x -q                                 # stop at the first failure
pytest --lf                                  # only what failed last time
pytest eds/tests/test_retail_temporal.py     # the temporal suite, ~4 min
```

### The four gates — all must pass

```bash
pytest                      # 2413 passed, 1 deselected
ruff check .                # All checks passed!
ruff format --check .       # 440 files already formatted
mypy eds                    # no issues in 365 source files
```

Run all four before you consider a change finished. There is **no CI
configuration in the repository — the gates are run by hand.**

---

## 7. Useful commands

| Task | Command |
| --- | --- |
| Version | `eds version` |
| Help for any command | `eds generate commerce --help` |
| Generate everything | `eds generate master-data && eds generate customers && eds generate journey && eds generate commerce` |
| Generate elsewhere | `eds generate master-data --output ./scratch` |
| Different seed | `eds generate master-data --seed 7` |
| Smaller run | `eds generate customers --customers 50` |
| Validate without writing | `eds generate master-data --dry-run` |
| Alternative configuration | `eds generate master-data --config-dir ./configs-big` |
| Skip validation (debugging only) | `eds generate master-data --no-validate` |
| Tests | `pytest` |
| Long simulations | `pytest -m slow` |
| Lint | `ruff check .` |
| Fix formatting | `ruff format .` |
| Types | `mypy eds` |
| List the plan | `python -c "from eds.platform.execution import plan_domain; import eds.domains.retail; [print(s.stage_id, s.requires) for s in plan_domain('retail').stages]"` |

---

## 8. Repository tour — 5 minutes

Read these six files, in this order. Ninety per cent of the design is in them.

| # | File | Why |
| --- | --- | --- |
| 1 | `eds/core/schema.py` | `Dataset` — the declaration everything reads |
| 2 | `eds/platform/domain.py` | What a domain must provide, and what it must not |
| 3 | `eds/domains/retail/registry.py` | How Retail describes itself, derived not restated |
| 4 | `eds/platform/scheduler/scheduler.py` | The whole execution loop. Read the module docstring |
| 5 | `eds/runners/retail/executor.py` | The seam between the platform and a domain |
| 6 | `eds/domains/retail/temporal/day.py` | How a business day works. "A stage founds itself" |

**Module docstrings explain *why*, not what.** They are the primary
documentation — read them before the code.

### Layers at a glance

```
eds/core/        Shared vocabulary. No business, no storage
eds/platform/    How to RUN a simulation. Knows no business
eds/domains/     WHAT is simulated. Knows nothing about being run
eds/adapters/    WHERE data goes. The Store of Record
eds/runners/     The only package that may import both sides
eds/cli/         The `eds` command. Predates the platform
```

Two rules explain the rest:

* The platform never imports a domain.
* A domain never imports the platform's runtime.

Tests enforce both by walking the AST. If a boundary test fails, your code is in
the wrong package — see [Maintainer Guide §2](03_Maintainer_Guide.md#2-architectural-boundaries).

### Where things live

| Looking for… | Go to |
| --- | --- |
| A dataset's columns | `eds/domains/retail/domain/<area>/schema.py` |
| How a dataset is generated | `eds/domains/retail/generators/` |
| A business rule | `eds/domains/retail/validation/` |
| A configuration default | `eds/domains/retail/config.py` |
| What a day does to the business | `eds/domains/retail/temporal/` |
| Why a decision was made | `docs/platform/PADR-*.md`, `docs/architecture/ADR-*.md` |

---

## 9. Debugging tips

### Exit codes tell you the layer

| Code | Meaning | Look at |
| --- | --- | --- |
| `2` | Configuration error, or a missing upstream dataset | Command order; `--output` / `--source` paths; your YAML |
| `3` | Validation failure. **Nothing was written** | The listed issues — each names a dataset and a rule |
| `4` | Could not write | Permissions, disk, output path |

### Inspect without writing

```bash
eds generate master-data --dry-run
```

Generates and validates, writes nothing. The fastest way to check a configuration
change.

### Isolate a validation failure

```bash
eds generate commerce --no-validate --output ./broken
```

Then inspect `./broken` and run the validator yourself:

```python
import polars as pl
from eds.domains.retail.validation.order_validation import validate_order_data

names = ["orders", "order_lines", "checkout", "customers", "products", "shopping_carts"]
data = {n: pl.read_parquet(f"broken/{n}.parquet") for n in names}
for issue in validate_order_data(data):
    print(issue)
```

Validators **return** issues rather than raising, so they are easy to call
directly.

### Read a report instead of a log

**Logging is not implemented in EDS v1.0** — there are no log files and no
verbosity flag. The programmatic API returns something better, because you can
assert on it:

```python
report = execute(run, RetailExecutor())

if not report.succeeded:
    f = report.result.failure
    print(f.failure_type, f.stage, f.message)
    print("cause:", f.cause)

for event in report.events:
    print(event.sequence, type(event).__name__, event.simulation_date)
```

`execute()` **never raises for a failed run** — check `report.succeeded`.

### Inspect the plan

```python
import eds.domains.retail  # registers the domain
from eds.platform.execution import plan_domain

plan = plan_domain("retail")
for stage in plan.stages:
    print(stage.stage_id)
    print("   requires:", stage.requires)
    print("   produces:", len(stage.produces), "datasets")
```

### Inspect a project's state

```bash
cat my-shop/state.json
```

```json
{
  "completed_stages": ["retail:master-data", "retail:customers",
                       "retail:journey", "retail:commerce"],
  "current_date": "2026-01-03",
  "last_identifiers": {},
  "state_version": 1
}
```

### Common surprises

| Symptom | Cause |
| --- | --- |
| `RunValidationError: clock_state_mismatch` | The clock does not start where the project stopped. Carrying a project forward across separate runs is **not implemented in EDS v1.0** — run the whole period in one call |
| `RunValidationError: nothing_to_resume` | `RunMode.RESUME` where every stage already completed |
| `KeyError: 'has not declared how it behaves over time'` | A new dataset without a temporality — see [Maintainer Guide §4](03_Maintainer_Guide.md#4-how-to-add-a-dataset) |
| Two runs differ | Seed is `null`, or the configuration directory or dates differ |
| `UnicodeEncodeError` on Windows | Legacy console code page. `set PYTHONIOENCODING=utf-8` |
| A run seems to hang | Generation is silent and CPU-bound. `journey` is the longest stage. Reduce `customer_count` |
| A test is slow | The temporal module runs real simulations. Use `-k` to narrow |

---

## 10. Contribution workflow

```
1. Read the decision records that touch what you are changing
      docs/platform/README.md   (PADR index — the platform's rules)
      docs/architecture/README.md (ADR index — Retail's business rules)

2. Write the test first. Name it as a sentence about behaviour.
      def test_a_payment_cannot_settle_an_order_that_was_never_placed() -> None:
          """It takes two days to break this; one day's output cannot."""

3. Make the change. Match the surrounding style:
      frozen dataclasses, Google docstrings, full type annotations,
      derive rather than restate

4. Run all four gates
      pytest && ruff check . && ruff format --check . && mypy eds

5. If you touched generation, verify determinism
      regenerate and compare per-file SHA-256 digests

6. Update the documentation that your change makes untrue
      the five suite documents, the PADR/ADR indexes, the roadmap

7. If you found a flaw in a frozen module — DOCUMENT it, do not
   silently change it. That habit is why this design is traceable.
```

**No `CONTRIBUTING.md`, `CHANGELOG.md`, CI configuration, pre-commit
configuration or `Makefile` exists in the repository.** The workflow above and
the four gates are the process.

Full review checklist: [Maintainer Guide §11](03_Maintainer_Guide.md#11-review-checklist).

---

## 11. A first change to try

**Add a configuration setting, end to end.** It touches every layer you need to
understand and cannot break anything.

Suppose reviews should be able to include a "would recommend" flag rate.

**1. The model** — `eds/domains/retail/config.py`, in `ReviewConfig`:

```python
recommend_rate: float = Field(default=0.8, ge=0.0, le=1.0)
```

Add it to the class docstring's `Attributes:` block.

**2. The YAML** — `configs/reviews.yaml`, with a comment saying what it means:

```yaml
# Share of reviewers who would recommend the product.
recommend_rate: 0.8
```

**3. A test** — `eds/tests/test_config.py`:

```python
def test_the_recommend_rate_must_be_a_share() -> None:
    """A rate outside 0..1 is a configuration error, not a surprise later."""
    with pytest.raises(ValidationError):
        ReviewConfig(recommend_rate=1.5)
```

**4. The gates**:

```bash
pytest -k recommend && ruff check . && ruff format --check . && mypy eds
```

What you will have learned: where configuration lives and why it is split
(PADR-007), that models are frozen and forbid unknown keys, that a bad value must
fail at load, and how tests are named.

**Then try**: use the setting in `eds/domains/retail/generators/commerce/review_generator.py`.
Now you are changing generated data, so the determinism check applies — and you
will see why it matters.

### Do not start with

* Adding a dataset — needs a temporality decision and re-baselined digests.
* Adding a domain — the deep end, though it should require no platform change.
* Anything in `eds/platform/` — frozen, and a change needs a PADR.

---

## 12. Checklist

Onboarding:

- [ ] `python --version` is 3.12+
- [ ] `pip install -e ".[dev]"` succeeded
- [ ] `eds version` prints `0.1.0`
- [ ] Four generate commands produced 39 files in `output/`
- [ ] Read one Parquet file with Polars
- [ ] Joined two datasets successfully
- [ ] Two identical runs produced identical digests
- [ ] Ran a three-day programmatic simulation
- [ ] Inspected `manifest.json` and `state.json`
- [ ] `pytest` green — 2,413 passed, 1 deselected
- [ ] All four gates green
- [ ] Read the six tour files
- [ ] Skimmed the PADR index

Before your first pull request:

- [ ] The relevant decision records read
- [ ] A test written before the change
- [ ] All four gates green
- [ ] Determinism verified, if generation changed
- [ ] Documentation updated
- [ ] Nothing unimplemented described as working

---

**Next:** [Handbook](01_Handbook.md) for concepts and configuration ·
[Architecture Reference](02_Architecture_Reference.md) for why the design is what
it is · [Maintainer Guide](03_Maintainer_Guide.md) before changing anything
structural · [Package Reference](04_Package_Reference.md) to find a class or
function.
