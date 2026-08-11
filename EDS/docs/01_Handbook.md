# Enterprise Data Simulator — Handbook

**EDS v1.0 · Official documentation · Document 1 of 5**

Audience: everyone. This document assumes no prior knowledge of EDS.

Companion documents: [Architecture Reference](02_Architecture_Reference.md) ·
[Maintainer Guide](03_Maintainer_Guide.md) ·
[Package Reference](04_Package_Reference.md) ·
[Developer Quick Start](05_Developer_Quick_Start.md) ·
[Documentation index](README.md)

---

## Table of contents

1. [Introduction](#1-introduction)
2. [What is Enterprise Data Simulator](#2-what-is-enterprise-data-simulator)
3. [Why EDS exists](#3-why-eds-exists)
4. [Problems it solves](#4-problems-it-solves)
5. [Core concepts](#5-core-concepts)
6. [Overall architecture](#6-overall-architecture)
7. [Repository layout](#7-repository-layout)
8. [Installation](#8-installation)
9. [Prerequisites](#9-prerequisites)
10. [Configuration](#10-configuration)
11. [Running the simulator](#11-running-the-simulator)
12. [Generated outputs](#12-generated-outputs)
13. [Logs](#13-logs)
14. [Typical workflows](#14-typical-workflows)
15. [Understanding the generated data](#15-understanding-the-generated-data)
16. [Common mistakes](#16-common-mistakes)
17. [Troubleshooting](#17-troubleshooting)
18. [Frequently asked questions](#18-frequently-asked-questions)
19. [Glossary](#19-glossary)
20. [Next steps](#20-next-steps)

---

## 1. Introduction

Enterprise Data Simulator (EDS) generates synthetic enterprise datasets by
simulating business events.

By the end of this document you will be able to install EDS, generate a complete
retail enterprise, read the output, run a multi-day simulation, and know where to
look when something goes wrong.

**Getting started takes about ten minutes.** Generating a full enterprise at the
default scale takes under six seconds and produces 39 files totalling about 4 MB.

If you would rather work through commands than read prose, start with the
[Developer Quick Start](05_Developer_Quick_Start.md) and return here for
explanation.

---

## 2. What is Enterprise Data Simulator

EDS produces the data an enterprise would have accumulated, by simulating the
events that would have produced it.

At the default scale one run generates **39 referentially consistent datasets**
containing about **153,000 rows** — a complete retail business:

| Group | Datasets |
| --- | --- |
| Geography | `countries`, `states`, `cities` |
| Product catalogue | `categories`, `brands`, `products` |
| Supply chain | `suppliers`, `warehouses`, `inventory` |
| Commercial reference | `payment_methods`, `shipping_methods`, `tax_codes`, `coupon_types`, `return_reasons` |
| Customers | `customers`, `customer_addresses`, `customer_preferences`, `customer_loyalty` |
| Digital journey | `customer_personas`, `sessions`, `category_views`, `search_history`, `product_views`, `wishlists` |
| Commerce | `shopping_carts`, `cart_items`, `checkout`, `orders`, `order_lines`, `order_status_history` |
| Payments | `payments`, `payment_status_history` |
| Fulfilment | `shipments`, `shipment_items`, `shipment_status_history` |
| Returns | `returns`, `return_items`, `return_status_history` |
| Reviews | `reviews` |

Three properties distinguish it from a row generator.

**It simulates causality, not coincidence.** A review exists because a shipment
was delivered, which exists because a payment was captured, which exists because
an order was placed, which exists because a checkout succeeded, which exists
because a cart was filled during a browsing session by a customer who registered
on a particular day. Every row has a parent and a reason.

**It is deterministic.** The same seed produces byte-identical output on any
machine, on any day. There is no wall-clock dependency anywhere in generation.

**It evolves over simulated time.** A simulation can run for one business day or
365 consecutive ones. Each day adds to the last: customers register, existing
customers return, stock is consumed and replenished, loyalty balances accrue.
Nothing already written is rewritten.

### What EDS is not

* **Not an anonymiser.** It does not read, mask or transform real data.
* **Not a load generator.** It writes files; it does not drive traffic.
* **Not a server.** There is no API, no UI and no daemon.
* **Not multi-domain yet.** Retail is the only domain in v1.0.

---

## 3. Why EDS exists

Realistic enterprise data is difficult to obtain and dangerous to copy.

Production data cannot be used for development, demonstration or testing without
legal and ethical risk, and masking it well is harder than it appears — masked
data usually loses the referential and temporal structure that made it useful.

The available alternatives fail in a specific way. Row generators produce tables
that are individually plausible and collectively incoherent: a payment for an
order that does not exist, a review of a product never shipped, a session by a
customer who registers three years later. Data like this passes a schema check
and fails the first meaningful query.

EDS takes the opposite approach: generate the *business*, and let the data be
what the business produced.

---

## 4. Problems it solves

| Problem | How EDS addresses it |
| --- | --- |
| No safe data for development or demos | Wholly synthetic; no real data is read |
| Test data lacks referential integrity | Every foreign key is generated from a real parent and validated |
| Test data has no temporal coherence | Events are ordered: a payment never precedes its order |
| Bugs cannot be reproduced | A seed reproduces a dataset exactly |
| Data volumes cannot be varied | Volumes are configuration; 20 customers or 100,000 |
| Time-series and history are missing | A run covers one day or a year of trading |
| Pipelines are only tested on a snapshot | A simulation can be stopped, resumed and continued |

---

## 5. Core concepts

Six concepts carry all the vocabulary in this documentation. The same terms are
used in all five documents.

### Enterprise

One simulated business, with an identity that outlives any single run. An
enterprise is represented by a **project**: a directory containing its datasets
and a small amount of recorded state.

Two runs against the same project continue the same enterprise. Two projects,
even with identical settings, are two different businesses.

### Domain

The *kind* of business being simulated — its entities, its generators, and its
rules. `retail` is the only domain in EDS v1.0.

A domain describes itself to the platform: which stages it has, what each stage
requires, and what each stage produces. It does not know how it is run, when it
is run, or where its data goes.

### Dataset

One named, schema-declared table of rows — `orders`, `customers`, `inventory`.
Each dataset declares its columns and types, its primary key, its unique columns
and its foreign keys, in one place, once. Everything else in the system reads
those declarations rather than restating them.

Each dataset also declares how it behaves when a simulated day passes:

| Behaviour | Meaning | Example |
| --- | --- | --- |
| **Static** | Written on the founding day, never again | `countries`, `products` |
| **Append-only** | History; rows are added, never altered | `orders`, `sessions` |
| **Mutable snapshot** | A picture of now, replaced when it changes | `inventory` |
| **Slowly changing** | One row per subject, a few attributes move | `customer_loyalty` |

### Business Context

The entire hand-over from the platform to a domain: **a business date and a
seed**. Nothing else.

A domain cannot ask what time it is and cannot advance time. It is told which day
it is trading on, and it trades. This is what allows the same domain code to be
used for a one-day snapshot and for a year of history.

### Simulation Time

Time inside a simulation, owned entirely by the platform. It has four parts:

* a **period** — the first and last business date;
* a **tick** — what one step is worth (1 day, 1 week, 1 month, 1 business day…);
* a **calendar** — which days count as business days;
* a **clock** — where in the period the simulation currently stands.

Simulated time is never wall-clock time. A run covering January 2026 produces
January 2026 data whenever it is executed.

### Store of Record

The project's own copy of its data: complete, readable, and the authoritative
statement of what the enterprise is.

This matters more than it sounds. A domain works out what to do next entirely by
reading what it has already written — whether it is founding a business or
continuing one, which identifiers have been issued, what the business currently
looks like. **The data is the state.** There is no checkpoint file, no tick
counter and no "first run" flag anywhere in EDS.

In v1.0 the store of record is a directory of Parquet files.

---

## 6. Overall architecture

Five layers, with a dependency direction enforced by tests.

```
                    ┌──────────────────────────────┐
                    │        eds.platform          │  How to RUN a simulation
                    │  plan · project · time ·     │  Knows no business
                    │  run · contracts · scheduler │
                    └──────────────────────────────┘
                                   ▲
                                   │
                    ┌──────────────────────────────┐
                    │         eds.runners          │  The integration boundary
                    │  the only package that may   │  Translates, wires,
                    │  import both sides           │  classifies failures
                    └──────┬────────────┬──────────┘
                           │            │
              ┌────────────┘            └────────────┐
              ▼                                      ▼
   ┌─────────────────────┐                ┌─────────────────────┐
   │    eds.domains      │                │    eds.adapters     │
   │  WHAT is simulated  │                │  WHERE data goes    │
   │  retail entities,   │                │  Parquet read/write │
   │  generators, rules  │                │  = Store of Record  │
   └─────────────────────┘                └─────────────────────┘
              │                                      │
              └──────────┐            ┌──────────────┘
                         ▼            ▼
                    ┌──────────────────────────────┐
                    │          eds.core            │  Shared vocabulary
                    │  schema · frames · seeds ·   │  No business,
                    │  validation · config loading │  no storage format
                    └──────────────────────────────┘
```

Two rules explain most of the design:

* **The platform never imports a domain.** That is what allows a second domain to
  be added without editing platform code.
* **A domain never imports the platform's runtime.** That is what allows a domain
  to be used without a scheduler, and what keeps business logic out of the
  machinery.

Since neither may import the other, something has to translate — and that is
`eds.runners`, the only package permitted to import both.

Full treatment, including all seventeen architecture decision records, is in the
[Architecture Reference](02_Architecture_Reference.md).

---

## 7. Repository layout

```
EDS/
├── configs/                  Configuration. One YAML file per feature
├── docs/
│   ├── 01_Handbook.md        ← this document
│   ├── 02_Architecture_Reference.md
│   ├── 03_Maintainer_Guide.md
│   ├── 04_Package_Reference.md
│   ├── 05_Developer_Quick_Start.md
│   ├── platform/             Platform vision, architecture, roadmap, PADR-001..017
│   ├── architecture/         Retail decision records, ADR-001..014
│   └── features/             One folder per feature: context, prompt, review
├── eds/
│   ├── core/                 Shared infrastructure. No business, no storage
│   ├── platform/             Simulation lifecycle
│   │   ├── execution/        Planning — what runs, in what order
│   │   ├── project/          Durable identity and recorded state
│   │   ├── time/             Period, tick, calendar, clock
│   │   ├── run/              Project + plan + clock, bound and validated
│   │   ├── runtime/          Results, events, failures — facts, no behaviour
│   │   └── scheduler/        Executes a simulation
│   ├── domains/retail/       The Retail domain
│   │   ├── domain/           Entity schemas and enums
│   │   ├── generators/       Business event generators
│   │   ├── temporal/         What one simulated day does to the business
│   │   └── validation/       Retail business rules
│   ├── adapters/             Parquet read and write — the Store of Record
│   ├── runners/retail/       Retail wired into the platform
│   ├── cli/                  The `eds` command-line interface
│   ├── tests/                2,414 tests
│   └── domain/ generators/ validation/ exporters/ config.py
│                             Pre-platform import paths, kept working
├── pyproject.toml            Packaging, dependencies, mypy settings
├── pytest.ini                Test configuration and markers
├── ruff.toml                 Lint and format configuration
└── README.md
```

### Packages reserved but empty in v1.0

These exist to mark where future work belongs. Each contains only a docstring.

`eds/events/`, `eds/simulation/`, `eds/state/`, `eds/workflows/`,
`eds/exporters/csv/`, `eds/exporters/delta/`, `eds/exporters/sql/`,
`eds/platform/state.py`.

**Not implemented in EDS v1.0.**

---

## 8. Installation

```bash
# 1. Get the repository, then from its root:
python -m venv .venv

# 2. Activate it
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows PowerShell
source .venv/Scripts/activate    # Windows Git Bash

# 3. Install EDS and the development tools, editable
pip install -e ".[dev]"

# 4. Verify
eds version
```

Expected output:

```
0.1.0
```

If `eds` is not found, the virtual environment is not active, or the install used
a different interpreter. `python -m eds.cli.main version` works either way and is
a useful check.

---

## 9. Prerequisites

| Requirement | Value |
| --- | --- |
| Python | 3.12 or later. Developed and tested on 3.13 |
| Operating system | Any supported by Python. Developed on Windows 10 |
| Disk | ~5 MB for a default-scale run; ~1 MB for the repository |
| Memory | Datasets are built in memory. Default scale is comfortable in well under 1 GB |
| Network | None. EDS makes no network calls |
| Database | None. Output is Parquet files |

### Runtime dependencies

| Package | Role |
| --- | --- |
| `polars` ≥ 1.0 | DataFrames and Parquet I/O |
| `pydantic` ≥ 2.7 | Configuration validation |
| `faker` ≥ 25.0 | Names, addresses and other realistic strings |
| `typer` ≥ 0.12 | The command-line interface |
| `pyyaml` ≥ 6.0 | Reading configuration files |

Development extras: `pytest`, `ruff`, `mypy`, `types-PyYAML`.

---

## 10. Configuration

Configuration lives in `configs/` — one YAML file per feature. Every file is
validated on load; a bad value fails immediately with a precise message rather
than part-way through a long run.

| File | Governs |
| --- | --- |
| `simulation.yaml` | Seed, timezone, locale, output directory |
| `logging.yaml` | Logging defaults. **See [§13](#13-logs)** |
| `master_data.yaml` | Entity volumes, category tree shape, geographic coverage |
| `customers.yaml` | Customer count, addresses per customer, registration window, reference date |
| `journey.yaml` | Bounce rate, page ceiling, session window |
| `browsing.yaml` | Category views and searches per session, view durations |
| `engagement.yaml` | Product views per category view, dwell times, wishlist rate |
| `commerce.yaml` | Cart rate, quantities, cart size ceiling, removal rate |
| `checkout.yaml` | Tax band, address reuse, checkout duration |
| `orders.yaml` | Lifecycle rates, transition waits, order number prefix |
| `payments.yaml` | Currency, capture/void/failure rates, reference prefix |
| `shipments.yaml` | Carriers and delivery windows per method, completion rates, prefixes |
| `returns.yaml` | Return rate, refund types, lifecycle rates, prefix |
| `reviews.yaml` | Review rate, rating weights, titles and bodies, writing delay, prefix |
| `evolution.yaml` | How much business one simulated *day* brings. **Optional** |

### Precedence

```
command-line flag   →   YAML file   →   model default
   (highest)                              (lowest)
```

A setting absent from a YAML file falls back to the model default in
`eds/domains/retail/config.py`, so a valid configuration directory need not be
exhaustive. `evolution.yaml` may be absent entirely; every other file must exist
in the directory being used.

### The seed

`configs/simulation.yaml`:

```yaml
seed: 42
timezone: UTC
locale: en_US
output_directory: output
```

The seed is what makes a run reproducible. Setting it to `null` produces a
non-deterministic run — in which case the seed actually used is printed, so the
run can be replayed exactly.

### Changing volumes

```yaml
# configs/customers.yaml
customer_count: 5000            # was 1000
```

```yaml
# configs/master_data.yaml
product_count: 10000            # was 1000
warehouses_per_product: 3
```

Journey and commerce volumes follow from the customer count: more customers means
more sessions, which means more carts, orders and reviews.

### Using a different configuration directory

Every `eds generate` command accepts `--config-dir`, so alternative
configurations do not require editing the repository:

```bash
cp -r configs configs-large
# edit configs-large/customers.yaml
eds generate master-data --config-dir configs-large --output out-large
```

---

## 11. Running the simulator

EDS has two ways to run, and the difference matters.

| | Command line | Programmatic |
| --- | --- | --- |
| Produces | One snapshot of an enterprise | One *or many* business days |
| Simulated time | A single implicit date | An explicit clock and period |
| Project / resume | No | Yes |
| Interface | `eds generate …` | Python API |

**A command-line interface for multi-day simulation, projects or resuming is
not implemented in EDS v1.0.** Time-aware simulation is available through the
Python API only.

### 11.1 Command line — a single snapshot

Four commands, run in order. Each reads what the previous one wrote.

```bash
eds generate master-data
eds generate customers
eds generate journey
eds generate commerce
```

Output goes to `output/` by default (`output_directory` in `simulation.yaml`).

Alongside the Parquet files, each command also writes/updates
`output/schema.json`: a plain-JSON description of every dataset written so
far (primary key, foreign keys, unique columns, column types), merged
across the four commands regardless of the order they're run in. It exists
so a consumer that is not EDS itself -- the Loader Tool, in particular --
can know a dataset's constraints without importing any EDS Python code. See
`eds.core.schema_export` in the Package Reference.

Real output from the last command:

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

Measured timings at default scale (1,000 customers, 1,000 products):

| Command | Time |
| --- | --- |
| `master-data` | 0.4 s |
| `customers` | 0.9 s |
| `journey` | 3.3 s |
| `commerce` | 1.1 s |
| **Total** | **5.7 s → 39 files, 4.1 MB** |

#### Options

Common to all four commands:

| Option | Effect |
| --- | --- |
| `--seed <int>` | Override the configured seed |
| `--output <path>` | Where Parquet files are written |
| `--config-dir <path>` | Which configuration directory to read |
| `--validate` / `--no-validate` | Validate before writing. Default: validate |
| `--dry-run` | Generate and validate, write nothing |

Command-specific:

| Command | Option | Effect |
| --- | --- | --- |
| `master-data` | `--products`, `--warehouses`, `--suppliers` | Override volumes |
| `customers` | `--customers` | Override customer count |
| `customers` | `--master-data <path>` | Where to read master data from. Defaults to `--output` |
| `journey`, `commerce` | `--source <path>` | Where to read earlier datasets from. Defaults to `--output` |

Writing to and reading from separate directories:

```bash
eds generate master-data --output ./master
eds generate customers   --output ./cust --master-data ./master
```

#### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `2` | Configuration error — bad settings, or a required upstream dataset is missing |
| `3` | Validation failure — generated data broke a business rule. Nothing was written |
| `4` | Export failure — the data could not be written |

### 11.2 Programmatic — a multi-day simulation

This is how a simulation covering more than one business day is run.

```python
from datetime import date
from pathlib import Path

from eds.platform.project.project import create_project
from eds.platform.run.configuration import RunConfiguration
from eds.platform.run.run import create_run
from eds.platform.run.stop import AfterTicks
from eds.platform.scheduler.scheduler import execute
from eds.platform.time.clock import create_clock
from eds.runners.retail import RetailExecutor

# 1. An enterprise, with a durable identity
project = create_project(Path("./my-shop"), name="Demo Shop", domain="retail", seed=42)

# 2. Three consecutive business days
clock = create_clock(date(2026, 1, 1), end=date(2026, 1, 3))

# 3. Bind project + plan + clock into one validated run
run = create_run(project, clock, RunConfiguration(stop_condition=AfterTicks(3)))

# 4. Execute
report = execute(run, RetailExecutor())

print(report.result.status)  # completed
print(report.progress.completed_ticks)  # 3
for stage in report.result.stages:
    print(stage.stage_id, stage.status, stage.start_date, "->", stage.end_date)
```

Real output:

```
completed
3
retail:master-data completed 2026-01-01 -> 2026-01-03
retail:customers   completed 2026-01-01 -> 2026-01-03
retail:journey     completed 2026-01-01 -> 2026-01-03
retail:commerce    completed 2026-01-01 -> 2026-01-03
```

The first day **founds** the enterprise — it produces the same complete snapshot
the CLI does. Every day after that **evolves** it.

#### Run configuration

```python
RunConfiguration(
    mode=RunMode.FULL,  # FULL | TARGETED | RESUME
    targets=(),  # stage names, for TARGETED
    stop_condition=AfterTicks(30),  # AfterTicks | EndOfPeriod | AfterStage
    dry_run=False,  # rehearse: report what would run, write nothing
)
```

| Stop condition | Stops when |
| --- | --- |
| `EndOfPeriod()` | The clock reaches the end of its period |
| `AfterTicks(n)` | `n` business days have been executed |
| `AfterStage("customers")` | That stage completes, part-way through a day |

#### Ticks other than one day

```python
from eds.platform.time.tick import MONTHLY

clock = create_clock(date(2026, 1, 1), end=date(2026, 12, 31), tick=MONTHLY)
```

Available ticks: `DAILY`, `WEEKLY`, `MONTHLY`, `YEARLY`, and `Tick(n, unit)` for
any size, including `BUSINESS_DAY`.

#### Business calendars

```python
from eds.platform.time.calendar import BusinessCalendar

calendar = BusinessCalendar(weekend_days=(5, 6), holidays=(date(2026, 12, 25),))
clock = create_clock(date(2026, 1, 1), end=date(2026, 3, 31), calendar=calendar)
```

The default is `ContinuousCalendar` — every day is a business day.

---

## 12. Generated outputs

### 12.1 A CLI run

One directory of Parquet files, one file per dataset:

```
output/
├── brands.parquet
├── cart_items.parquet
├── categories.parquet
└── … 39 files in total
```

Snappy-compressed Parquet, readable by Polars, pandas, DuckDB, Spark, and most
warehouse loaders.

**Parquet is the only output format in EDS v1.0.** CSV, SQL and Delta packages
exist but are empty — see [§7](#7-repository-layout). Delivery to databases or
APIs is **not implemented in EDS v1.0**; it exists as design documentation only.

### 12.2 A project

```
my-shop/
├── manifest.json      The enterprise's identity. Written once, never changed
├── state.json         What has been done so far
└── data/              The Store of Record — 39 Parquet files
```

`manifest.json` from a real run:

```json
{
  "created_at": "2026-07-30T04:22:17.561492+00:00",
  "domain": "retail",
  "manifest_version": 1,
  "name": "Demo Shop",
  "platform_contract_version": 1,
  "platform_version": "0.1.0",
  "project_id": "a459a378e105454594355bfa1e88d388",
  "seed": 42
}
```

`state.json` after three days:

```json
{
  "completed_stages": [
    "retail:master-data",
    "retail:customers",
    "retail:journey",
    "retail:commerce"
  ],
  "current_date": "2026-01-03",
  "last_identifiers": {},
  "state_version": 1
}
```

The workspace also defines `snapshots/` and `logs/` directories. They are
reserved and **not created in EDS v1.0**.

### 12.3 Row counts at default scale

Seed 42, 1,000 customers, 1,000 products — measured, not estimated:

| Dataset | Rows | | Dataset | Rows |
| --- | ---: | --- | --- | ---: |
| `countries` | 1 | | `sessions` | 5,752 |
| `states` | 51 | | `category_views` | 28,310 |
| `cities` | 255 | | `search_history` | 11,460 |
| `categories` | 168 | | `product_views` | 88,248 |
| `brands` | 50 | | `wishlists` | 988 |
| `products` | 1,000 | | `shopping_carts` | 914 |
| `suppliers` | 25 | | `cart_items` | 1,703 |
| `warehouses` | 10 | | `checkout` | 376 |
| `inventory` | 3,000 | | `orders` | 311 |
| `payment_methods` | 13 | | `order_lines` | 513 |
| `shipping_methods` | 9 | | `order_status_history` | 879 |
| `tax_codes` | 7 | | `payments` | 309 |
| `coupon_types` | 8 | | `payment_status_history` | 596 |
| `return_reasons` | 5 | | `shipments` | 283 |
| `customers` | 1,000 | | `shipment_items` | 469 |
| `customer_addresses` | 1,495 | | `shipment_status_history` | 1,379 |
| `customer_preferences` | 1,000 | | `returns` | 35 |
| `customer_loyalty` | 1,000 | | `return_items` | 42 |
| `customer_personas` | 1,000 | | `return_status_history` | 168 |
| | | | `reviews` | 58 |

**Total: 152,890 rows across 39 datasets.**

---

## 13. Logs

**Logging is not implemented in EDS v1.0.**

`configs/logging.yaml` exists and its structure is covered by tests, but **no
module in `eds/` reads it and no component emits log records.** There is no
logger configuration, no log file and no verbosity flag.

What you get instead:

* **The CLI prints a summary** — validation result, seed, output directory, and
  per-dataset row counts (see [§11.1](#111-command-line--a-single-snapshot)).
* **The programmatic API returns a report.** An `ExecutionReport` carries the run
  result, a numbered event stream and progress. This is richer than a log,
  because it is a value you can assert on:

```python
for event in report.events:
    print(event.sequence, type(event).__name__, event.simulation_date)
```

```
0 RunStarted     2026-01-01
1 StageStarted   2026-01-01
2 StageCompleted 2026-01-01
…
```

* **Failures are values, not exceptions.** `execute()` does not raise for a
  failed run; `report.result.failure` describes what happened, of what kind, at
  which stage and on which date.

---

## 14. Typical workflows

### Generate a snapshot for a demo

```bash
eds generate master-data && eds generate customers \
  && eds generate journey && eds generate commerce
```

### Generate a larger enterprise without touching the repository

```bash
cp -r configs configs-big
sed -i 's/customer_count: 1000/customer_count: 20000/' configs-big/customers.yaml
eds generate master-data --config-dir configs-big --output big
eds generate customers   --config-dir configs-big --output big
eds generate journey     --config-dir configs-big --output big
eds generate commerce    --config-dir configs-big --output big
```

### Check a configuration change without writing anything

```bash
eds generate master-data --dry-run
```

### Simulate a month of trading

```python
clock = create_clock(date(2026, 1, 1), end=date(2026, 1, 31))
report = execute(
    create_run(project, clock, RunConfiguration(stop_condition=AfterTicks(31))),
    RetailExecutor(),
)
```

### Reproduce someone else's dataset

Match three things: the seed, the configuration directory, and the business
date(s). Nothing else affects the output.

### Generate a smaller enterprise for a test

```python
from eds.domains.retail.config import load_config

config = load_config()
small = config.model_copy(
    update={
        "customers": config.customers.model_copy(update={"customer_count": 20}),
        "master_data": config.master_data.model_copy(update={"product_count": 30}),
    }
)
report = execute(run, RetailExecutor(config=small))
```

---

## 15. Understanding the generated data

### The chain

Each link narrows the one before it. At default scale:

```
5,752 sessions
   └─▶   914 carts          (a session may open a cart)
          └─▶ 376 checkouts (a cart may reach checkout)
               └─▶ 311 orders     (a checkout may succeed)
                    └─▶ 309 payments
                         └─▶ 283 shipments
                              ├─▶  35 returns   (a delivery may come back)
                              └─▶  58 reviews   (a kept item may be reviewed)
```

Every drop-off is a business rule, not an accident: a bounce rate, a cart
abandonment rate, a payment failure rate, a return rate, a review rate — each
configurable.

### Joining the data

```python
import polars as pl

orders = pl.read_parquet("output/orders.parquet")
customers = pl.read_parquet("output/customers.parquet")

revenue = (
    orders.join(customers, on="customer_id")
    .group_by("customer_segment")
    .agg(pl.col("total_amount").sum().alias("revenue"))
    .sort("revenue", descending=True)
)
print(revenue)
```

Every foreign key resolves. There are no orphans, and this is validated on every
run rather than assumed.

### Guarantees you can rely on

| Guarantee | Detail |
| --- | --- |
| Primary keys | Unique in every dataset |
| Foreign keys | Every non-null value resolves to a parent row |
| Financial values | Copied from the checkout, never recomputed; totals reconcile |
| Temporal ordering | A session follows registration; a payment never precedes its order; a review never precedes delivery |
| Status history | State changes are recorded in `*_status_history` datasets, in sequence |
| Determinism | Same seed, same configuration, same dates → identical bytes |
| Monotonicity | Loyalty balances never decrease |

### What multi-day runs add

Only the first day founds; later days evolve.

| Dataset behaviour | What a later day does |
| --- | --- |
| Static | Nothing. Written once |
| Append-only | Adds rows. **Existing rows are byte-for-byte unchanged** |
| Mutable snapshot | Replaces `inventory` with current stock |
| Slowly changing | Updates loyalty balances in place; adds rows for new customers |

And one strong property worth knowing about: **how a run was divided does not
show in the data.** Nine days run at once and nine days run as four, then three,
then two produce identical bytes, because each day is seeded from its *date*
rather than its position.

---

## 16. Common mistakes

**Running the commands out of order.** `customers` reads what `master-data`
wrote. Out of order gives exit code 2.

**Expecting `--output` to be remembered.** It is per-command. Pass it to all
four, or accept the default for all four.

**Reading from the wrong directory.** If you split output across directories,
`--master-data` and `--source` must point at where the earlier data actually is.

**Assuming multi-day runs are available from the CLI.** They are not — see
[§11](#11-running-the-simulator).

**Expecting log files.** There are none. See [§13](#13-logs).

**Expecting two projects with the same seed to be identical.** The *data* will
match; `project_id` and `created_at` will not, by design.

**Editing `configs/` for a one-off.** Use `--config-dir`, or `model_copy` in
Python.

**Expecting a second run to continue where the last one stopped.** A run must
start where the project's recorded state says it stopped, and the scheduler
leaves the clock on the final executed day — so there is no date a follow-on run
can legally start on. Carrying a project forward across separate runs is
**not implemented in EDS v1.0**; run the whole period in one call.

**Treating a destination as a replacement for the Store of Record.** There are no
destinations in v1.0, but the principle matters if you write your own writer: the
project's readable copy is what the next day reads to know what has happened.

---

## 17. Troubleshooting

### `eds: command not found`

The virtual environment is not active, or `pip install -e ".[dev]"` was run with
a different interpreter. Use `python -m eds.cli.main` to confirm the package
itself is importable.

### Exit code 2 — configuration error

Three usual causes:

1. **A required upstream dataset is missing.** Run the commands in order, or
   check that `--master-data` / `--source` points at the right directory.
2. **A configuration value is out of range.** The message names the file and the
   field. Example: `customer_count` must be ≥ 1.
3. **The configuration directory is wrong or incomplete.** Every file except
   `evolution.yaml` must be present in the directory given by `--config-dir`.

### Exit code 3 — validation failure

Generated data broke a business rule. **Nothing was written.** The message lists
the first few issues, each naming the dataset and the rule. This normally means a
configuration combination the generators cannot satisfy; the issue text says
which rule failed.

### Exit code 4 — export failure

The datasets could not be written: a permission problem, a full disk, or an
output path that is not a directory.

### `RunValidationError: clock_state_mismatch`

The run's clock does not start where the project's recorded state says it
stopped. This is the limitation described in [§16](#16-common-mistakes): run the
whole period in one call.

### `RunValidationError: nothing_to_resume`

`RunMode.RESUME` was used against a project where every stage is already
recorded as completed. A resume needs outstanding work.

### The datasets differ between two runs

Check, in order: the seed (is it `null`?), the configuration directory, and the
business dates. If all three match and the output differs, that is a bug worth
reporting — determinism is a tested property.

### `UnicodeEncodeError` on Windows

Not an EDS fault. The Windows console defaults to a legacy code page and the CLI
prints box-drawing characters. Set `PYTHONIOENCODING=utf-8`.

### A run appears to hang

At large scale, generation is CPU-bound and silent — there is no progress output
([§13](#13-logs)). `journey` is the longest stage. Reduce `customer_count` to
confirm progress, then scale up.

---

## 18. Frequently asked questions

**Is any real data used?**
No. Nothing is read from any external source. Country and subdivision names are
real reference data; everything else is synthesised.

**Can I trust the referential integrity?**
Yes, and you do not have to take it on faith — every run validates it, and a
failure aborts before anything is written.

**How large can it go?**
Volumes are configuration. Memory is the practical limit, since datasets are
built in memory before being written. At default scale the whole enterprise is
about 4 MB.

**Can I generate only one dataset?**
Not individually. The smallest unit is a stage — one of the four commands.
Splitting stages further is not implemented in EDS v1.0.

**Can I add my own domain?**
Yes, and doing so should require no change to platform code. See the
[Maintainer Guide](03_Maintainer_Guide.md).

**Can I output to a database?**
Not in EDS v1.0. Design documentation exists
([P007B](platform/P007B-destination-adapter-framework.md),
[PADR-017](platform/PADR-017-enterprise-distribution-architecture.md)) but no
implementation.

**Is there an API or a UI?**
No. A CLI and a Python API.

**Why Parquet?**
It preserves types, compresses well, and every analytical tool reads it.

**What does the reference date mean?**
For a CLI run, it is the "as of" date the snapshot is generated relative to,
configured in `customers.yaml` (default 2026-01-01). For a programmatic run, the
business date supplied by the clock replaces it.

**Why is `product_views` so much larger than everything else?**
It is the finest-grained event in the journey: several product views per category
view, several category views per session, 5,752 sessions.

**Can I run two simulations at once?**
Yes, into different output directories or different projects. Nothing is shared
between them.

**Is EDS thread-safe / parallel?**
Execution is deliberately sequential. Parallelism is not implemented in EDS v1.0.

**What Python versions are supported?**
3.12 and later; 3.13 is what the suite runs on.

---

## 19. Glossary

The same terms are used across all five documents.

| Term | Meaning |
| --- | --- |
| **Adapter** | A component that reads and writes datasets. Parquet in v1.0 |
| **Append-only** | A dataset whose rows are added but never altered |
| **Business Context** | The business date and seed handed to a domain. Nothing else |
| **Business date** | The simulated date a unit of work belongs to |
| **Calendar** | Which days count as business days |
| **Clock** | Where a simulation stands in its period |
| **Dataset** | One named, schema-declared table |
| **Determinism** | Same inputs → identical bytes |
| **Domain** | A kind of business: its entities, generators and rules |
| **Enterprise** | One simulated business, represented by a project |
| **Execution plan** | The ordered stages a domain's declarations imply |
| **Founding** | The first unit of work for a stage; it builds a history |
| **Generator** | Code that produces one feature's datasets |
| **Project** | A directory holding an enterprise: manifest, state, data |
| **Reference date** | The "as of" date a snapshot is generated relative to |
| **Run** | One configured execution: project + plan + clock |
| **Runner** | The integration layer that teaches the scheduler to run a domain |
| **Scheduler** | The component that executes a run |
| **Seed** | The integer from which all randomness derives |
| **Stage** | A unit of the execution plan. Retail has four |
| **Store of Record** | The project's own complete, readable copy of its data |
| **Temporality** | How a dataset behaves when a day passes |
| **Tick** | One step of simulated time |
| **Validation** | Checking generated data against declared rules before writing |

---

## 20. Next steps

| If you want to… | Read |
| --- | --- |
| Be productive in half an hour | [Developer Quick Start](05_Developer_Quick_Start.md) |
| Understand why the design is what it is | [Architecture Reference](02_Architecture_Reference.md) |
| Add a domain, dataset or setting | [Maintainer Guide](03_Maintainer_Guide.md) |
| Find a class or function | [Package Reference](04_Package_Reference.md) |
| Understand Retail's business rules | [ADR-001 to ADR-014](architecture/README.md) |
| Understand the platform's rules | [PADR-001 to PADR-017](platform/README.md) |
| See what is planned but not built | [Roadmap](platform/03_Roadmap.md) |
