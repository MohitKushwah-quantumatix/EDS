# EDS Generator — Developer Guide

> **EDS v1.0 · How to run, configure, and schedule the Enterprise Data Simulator.**

---

## Table of Contents

1. [Before You Start](#1-before-you-start)
2. [Clone the Repository](#2-clone-the-repository)
3. [Create a Virtual Environment](#3-create-a-virtual-environment)
4. [Install Dependencies](#4-install-dependencies)
5. [Verify Installation](#5-verify-installation)
6. [Understand the Two Run Modes](#6-understand-the-two-run-modes)
7. [Run a Single Day — `run_day.py`](#7-run-a-single-day--run_daypy)
8. [Run Multi-Day Simulations — `cron_runner.py`](#8-run-multi-day-simulations--cron_runnerpy)
9. [Domain Configuration — `config.yaml`](#9-domain-configuration--configyaml)
10. [Change Simulation Parameters](#10-change-simulation-parameters)
11. [Schedule Timing — Testing vs Production](#11-schedule-timing--testing-vs-production)
12. [Output Structure](#12-output-structure)
13. [Backup and Crash Recovery](#13-backup-and-crash-recovery)
14. [Common Issues and Fixes](#14-common-issues-and-fixes)
15. [Quick Reference](#15-quick-reference)

---

## 1. Before You Start

| Requirement | Value |
| --- | --- |
| **Python** | 3.12 or later (3.13 recommended) |
| **OS** | Windows 10/11 or Ubuntu 20.04+ |
| **Disk** | ~50 MB for the project + output |
| **Network** | Required only for `pip install` |
| **Database** | None — SQLite is embedded and created automatically |

Check your Python version:

```bash
python --version        # Should show 3.12.x or later
```

---

## 2. Clone the Repository

```bash
git clone https://github.com/MohitKushwah-quantumatix/EDS.git
cd EDS
```

---

## 3. Create a Virtual Environment

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\activate
```

### Ubuntu

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Your prompt should change to show `(.venv)`.

---

## 4. Install Dependencies

### All Platforms

```bash
pip install -e .
```

This installs **all required dependencies** automatically:

| Package | Purpose |
| --- | --- |
| `polars` | DataFrame operations and Parquet I/O |
| `pydantic` | Configuration model validation |
| `faker` | Realistic synthetic data generation |
| `typer` | CLI (`eds` command) |
| `pyyaml` | YAML configuration parsing |
| `sqlalchemy` | SQLite adapter for simulation history |
| `pandas` | SQLite type coercion in the adapter |

> **Note:** The `[dev]` extras (pytest, ruff, mypy) are optional. Install them with
> `pip install -e ".[dev]"` if you plan to run tests or linting.

The `[postgres]` extras (`psycopg`, `pyarrow`) are only needed if you are
exporting to PostgreSQL — they are **not** required for the standard SQLite
workflow.

---

## 5. Verify Installation

```bash
python -c "import polars, pydantic, faker, typer, yaml, sqlalchemy, pandas; print('All imports OK')"
```

Expected output: `All imports OK`

---

## 6. Understand the Two Run Modes

EDS has **two entry points**, both in the project root:

| Script | Purpose |
| --- | --- |
| `run_day.py` | Run **one specific day** of simulation. Use this for testing, debugging, or running individual days manually. |
| `cron_runner.py` | Run a **full date range** automatically with scheduling. Use this for production or unattended runs. |

Both scripts use the same underlying simulation engine and produce identical output
for a given date.

---

## 7. Run a Single Day — `run_day.py`

### 7.1 Switch Domain in `config.yaml`

Before running, edit `config.yaml` to set the domain and project directory:

```yaml
domain: retail          # or "healthcare"
project_dir: my-shop    # or "my-hospital"
seed: 42
```

| Domain | `project_dir` value |
| --- | --- |
| `retail` | `my-shop` |
| `healthcare` | `my-hospital` |

### 7.2 Run the Day

```bash
# Windows
.venv\Scripts\python.exe run_day.py --domain retail --date 2026-01-01

# Ubuntu
.venv/bin/python run_day.py --domain retail --date 2026-01-01
```

#### Command-line Arguments

| Argument        | Required | Default                       | Description                            |
|   ---           |   ---    |   ---                         |   ---                                  |
| `--domain`      |   Yes    |   —                           |   `retail` or `healthcare`             |
| `--date`        |   Yes    |   —                           |   ISO date, e.g. `2026-01-01`          |
| `--project-dir` |   No     |   `my-shop` / `my-hospital`   |   Override the output directory        |
| `--seed`        |   No     |   `42`                        |   Random seed for determinism          |

### 7.3 What Happens on Day 1 (Founding Day)

1. A new SQLite database is created at `<project_dir>/.internal/simulation.db`
2. All master data is generated (countries, products, etc.)
3. **Retail:** 1,000 founding customers + their addresses, preferences, and loyalty records are created
4. **Healthcare:** 1,000 founding patients + their addresses, insurance, allergies, immunizations, and emergency contacts are created
5. Day-1 transactional data (sessions, orders, encounters, labs, etc.) is generated
6. Data is exported to `<project_dir>/output/*.parquet`
7. A backup is saved to `<project_dir>/.internal/backup.json.gz`
8. A checkpoint is saved to `<project_dir>/daily_checkpoint.json`

### 7.4 What Happens on Day 2+ (Evolving Days)

1. The checkpoint is read to determine the last completed day
2. The simulation generates **only new entities** for that day:
   - **Retail:** 5 new customers + their addresses, preferences, and loyalty
   - **Healthcare:** 5 new patients + their addresses, insurance, allergies, immunizations, and emergency contacts
3. **Existing** customers/patients also have day-appropriate activity:
   - Retail: returning customers open sessions, browse, and buy
   - Healthcare: existing patients have encounters, labs, admissions, etc.
4. All data is merged with history and written to SQLite
5. Only **today's date's data** is exported to `output/` (filtered by `created_at`)
6. Backup and checkpoint are updated

### 7.5 Run Days Sequentially

Run days in order — each day depends on the previous day's state:

```bash
# Day 1
python run_day.py --domain retail --date 2026-01-01

# Day 2
python run_day.py --domain retail --date 2026-01-02

# Day 3
python run_day.py --domain retail --date 2026-01-03
```

> **Do not skip days.** The simulation uses a checkpoint file to resume, but
> jumping from day 1 to day 3 without running day 2 will cause the simulation to
> generate day 2's data on day 3's date, producing incorrect results.

---

## 8. Run Multi-Day Simulations — `cron_runner.py`

`cron_runner.py` automates running all days from `start_date` to `end_date` in
`config.yaml`.

### 8.1 Configure `config.yaml`

```yaml
domain: retail
project_dir: my-shop
seed: 42

start_date: 2026-01-01
end_date: 2026-01-03

# Testing mode — 2 minutes between days
cron_interval_minutes: 2

# Production mode — run once per day at midnight
# cron_daily_time: "00:00"
```

### 8.2 Run the Cron Scheduler

```bash
# Windows
.venv\Scripts\python.exe cron_runner.py

# Ubuntu
.venv/bin/python cron_runner.py
```

### 8.3 How It Works

1. Reads `config.yaml` from the project root
2. Checks `<project_dir>/daily_checkpoint.json` to see where it left off
3. Runs each day from `start_date` to `end_date` in order
4. Between days:
   - **Testing mode:** waits `cron_interval_minutes` (default: 5 minutes)
   - **Production mode:** waits until `cron_daily_time` (e.g. midnight)
5. If interrupted, re-running `cron_runner.py` resumes from the last completed day

### 8.4 Resuming After a Crash

No special action needed. Just re-run `cron_runner.py` — it reads the checkpoint
and continues from the next uncompleted day.

---

## 9. Domain Configuration — `config.yaml`

The `config.yaml` in the project root controls the simulation run:

```yaml
# ── REQUIRED ──────────────────────────────────────────────────────────────────

domain: retail                    # "retail" or "healthcare"
project_dir: my-shop              # output folder name (created automatically)
seed: 42                          # deterministic seed; same seed = same output

# ── DATE RANGE ───────────────────────────────────────────────────────────────

start_date: 2026-01-01            # first day to simulate (inclusive)
end_date: 2026-01-03              # last day to simulate (inclusive)

# ── SCHEDULING ───────────────────────────────────────────────────────────────
# Choose ONE of the two modes below. Comment out the one you are NOT using.

# Testing mode — fast iteration
cron_interval_minutes: 2          # wait this many minutes between days

# Production mode — run once per day at a fixed time
# cron_daily_time: "00:00"         # 24-hour format, e.g. "00:00", "06:00"
```

### Domain Defaults

| `domain` value | Default `project_dir` | Run command shortcut |
| ---            | ---                   | ---                  |
| `retail`       | `my-shop`             | `run_day.py --domain retail --date <date>` |
| `healthcare`   | `my-hospital`         | `run_day.py --domain healthcare --date <date>` |

---

## 10. Change Simulation Parameters

All simulation parameters are defined in **Pydantic config models** under
`eds/domains/<domain>/config.py` and their corresponding YAML files under
`configs/`.

### 10.1 Quick-Override via `config.yaml`

For simple overrides (e.g. changing the seed or date range), edit `config.yaml`
directly:

```yaml
seed: 99
start_date: 2026-01-01
end_date: 2026-01-05
cron_interval_minutes: 1
```

### 10.2 Domain-Specific Parameters

To change business logic parameters (customer counts, rates, etc.), edit the
config models and their YAML files:

| What you want to change | File to edit | Key config section                                        |
| ---                     | ---          | ---                                                       |
| Customer count per day  | `configs/retail/evolution.yaml` (retail) | `evolution.new_customers_per_day` |
| Patient count per day   | `configs/healthcare/evolution.yaml` (healthcare) | `evolution.new_patients_per_day` |
| Product count           | `configs/retail/master_data.yaml` | `master_data.product_count`          |
| Session frequency       | `configs/retail/journey.yaml` | `journey.session_frequency`              |
| Loyalty points rate     | `configs/retail/evolution.yaml` | `evolution.loyalty_points_per_unit`  |
| Encounter rate          | `configs/healthcare/evolution.yaml` | `evolution.active_patient_rate`   |

### 10.3 Override Config Programmatically via `run_day.py`

You can pass config overrides as a Python dict when calling
`run_retail_day()` or `run_healthcare_day()` directly:

```python
from pathlib import Path
from run_day import run_retail_day

run_retail_day(
    project_dir=Path("my-shop"),
    target_date=date(2026, 1, 1),
    seed=42,
    config_overrides={
        "evolution": {"new_customers_per_day": 20},
        "master_data": {"product_count": 500},
    },
)
```

The `config_overrides` dict keys map to top-level attributes on the
`SimulationConfig` model. Nested sections are applied via `model_copy(update=...)`.

### 10.4 Healthcare-Specific Config Override Keys

When using `run_healthcare_day()` programmatically, the valid override keys are:

```python
config_overrides = {
    "master_data": {...},    # F001 master data settings
    "patients": {...},       # patient generation settings
    "providers": {...},      # provider generation settings
    "encounters": {...},     # encounter generation settings
    "billing": {...},        # billing and claims settings
    "evolution": {...},      # daily evolution rates
}
```

---

## 11. Schedule Timing — Testing vs Production

`cron_runner.py` supports two scheduling modes controlled by `config.yaml`:

### 11.1 Testing Mode

```yaml
cron_interval_minutes: 2
```

- Waits a fixed number of minutes between each day
- Best for local development and debugging
- Fast iteration — a 3-day simulation finishes in ~6 minutes

### 11.2 Production Mode

```yaml
# Comment out testing mode:
# cron_interval_minutes: 2

# Uncomment production mode:
cron_daily_time: "00:00"
```

- Waits until the specified time each day before running the next day
- Format: 24-hour `"HH:MM"` (e.g. `"06:00"`, `"14:30"`, `"23:45"`)
- Best for scheduled nightly runs or daily batch processing

### 11.3 How Scheduling Works

1. `cron_runner.py` calculates the total number of days: `(end_date - start_date).days + 1`
2. It reads `daily_checkpoint.json` to find the last completed day
3. For each remaining day:
   - If it's the first run or first day: runs immediately
   - If it's a subsequent day: sleeps until the next scheduled window
4. After each day completes, the checkpoint is updated
5. If the process is killed, re-running `cron_runner.py` resumes from the checkpoint

---

## 12. Output Structure

After running a day, the project directory looks like this:

```
my-shop/
├── .internal/
│   ├── simulation.db          # SQLite database with cumulative state
│   ├── backup.json.gz         # Compressed JSON backup for crash recovery
│   └── backup_schema.json     # Schema metadata for the backup
├── .loaded                    # Marker file indicating data is ready for the loader
├── daily_checkpoint.json      # Last completed simulation day
├── manifest.json              # Project identity and metadata
├── schema.json                # Polars schemas for all exported tables
├── state.json                 # Current simulation state
└── output/
    ├── brands.parquet
    ├── carts.parquet
    ├── customers.parquet
    ├── ...
    └── (39 parquet files for retail, 35 for healthcare)
```

### What's in `output/`

The `output/` folder contains **only the current day's data** for transactional
tables, filtered by `created_at` (or the table's primary date column). Master
/reference tables contain their full static data.

| Table type | Examples | Content in `output/` |
| --- | --- | --- |
| Master / reference | `countries`, `products`, `categories` | Full static data (unchanged every day) |
| Transactional — new entities | `customers`, `patients` | Only entities created on that day |
| Transactional — activity | `orders`, `encounters`, `lab_results` | Only activity that occurred on that day |
| Transactional — no date column | `customer_preferences` | Only records created on that day |

> The `output/` folder is **cleared and regenerated** on every day run. Do not
> modify files there — they are overwritten.

---

## 13. Backup and Crash Recovery

### 13.1 What Gets Backed Up

After each successful day, `save_backup()` writes all tables from the SQLite
database to `<project_dir>/.internal/backup.json.gz`. This is a compressed JSON
file containing:

- All table data (not just the last rows)
- Column schemas with exact Polars dtypes
- The domain name and last completed day

### 13.2 Automatic Recovery

If `run_day.py` or `cron_runner.py` is interrupted (power loss, crash, Ctrl+C):

1. On the next run, `load_backup()` reads `backup.json.gz`
2. All tables are restored into the SQLite adapter with correct types
3. The simulation resumes from `last_completed_day + 1`

No manual intervention is required — the checkpoint + backup system is fully
automatic.

### 13.3 Manual Recovery

If you need to restore from backup manually:

```python
from pathlib import Path
from run_day import load_backup
from eds.adapters.sqlite.adapter import SQLiteAdapter

adapter = SQLiteAdapter(db_path=Path("my-shop/.internal/simulation.db"))
restored_day = load_backup(Path("my-shop"), adapter)
print(f"Restored to: {restored_day}")
```

---

## 14. Common Issues and Fixes

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'sqlalchemy'` | Dependencies not installed | Run `pip install -e .` |
| `RunValidationError: clock_state_mismatch` | Running a day that doesn't follow the last checkpoint | Run days in order, or delete `daily_checkpoint.json` to reset |
| `RunValidationError: nothing_to_resume` | All days already completed | Delete `daily_checkpoint.json` if you want to re-run |
| `KeyError: 'has not declared how it behaves over time'` | A new dataset without a temporality declaration | Add the dataset to the temporality map in `temporal/temporality.py` |
| `UnicodeEncodeError` on Windows | Console code page issue | Set environment variable: `$env:PYTHONIOENCODING='utf-8'` (PowerShell) |
| `git push` rejected | Remote has commits you don't have locally | Run `git pull origin dev` first, resolve conflicts, then push |
| `customer_addresses` has old dates in output | Generated before the date-filtering fix | Delete the project folder and re-run from day 1 |
| Datetime displays as numbers on Ubuntu | SQLite stores datetimes as INTEGER on Linux | Already fixed in `adapter.py` — ensure you have the latest code |

### Reset a Project Completely

If you want to start a domain from scratch:

```bash
# Windows
Remove-Item -Recurse -Force my-shop

# Ubuntu
rm -rf my-shop
```

Then re-run from day 1. The SQLite database, checkpoint, and backup will all be
recreated fresh.

---

## 15. Quick Reference

### One-Liner Cheat Sheet

```bash
# ── Setup ──────────────────────────────────────────────────────────────────
python -m venv .venv
.venv\Scripts\activate              # Windows
source .venv/bin/activate           # Ubuntu
pip install -e .

# ── Single Day ─────────────────────────────────────────────────────────────
# Edit config.yaml first: set domain, project_dir, start_date, end_date
python run_day.py --domain retail --date 2026-01-01

# ── Multi-Day (cron) ────────────────────────────────────────────────────────
# Edit config.yaml: set cron_interval_minutes or cron_daily_time
python cron_runner.py

# ── Verify Output ───────────────────────────────────────────────────────────
python -c "import polars as pl; print(pl.read_parquet('my-shop/output/customers.parquet').head())"

# ── Tests ───────────────────────────────────────────────────────────────────
pytest                              # all tests
pytest -k "loyalty"                 # one test
pytest -m slow                      # long simulations

# ── Lint & Type Check ───────────────────────────────────────────────────────
ruff check .
ruff format .
mypy eds
```

### File Change Reference

| If you want to… | Change this file |
| --- | --- |
| Switch between retail and healthcare | `config.yaml` → `domain:` |
| Change date range | `config.yaml` → `start_date:` / `end_date:` |
| Change scheduling | `config.yaml` → `cron_interval_minutes:` or `cron_daily_time:` |
| Change output folder | `config.yaml` → `project_dir:` |
| Change customer/patient volumes | `configs/retail/evolution.yaml` or `configs/healthcare/evolution.yaml` |
| Change product/master data counts | `configs/retail/master_data.yaml` |
| Change business rates (loyalty, returns, etc.) | `configs/retail/*.yaml` or `configs/healthcare/*.yaml` |
| Change dataset schema (add a column) | `eds/domains/<domain>/domain/<area>/schema.py` |
| Change how data is generated | `eds/domains/<domain>/generators/<area>/` |
| Change what a day does to the business | `eds/domains/<domain>/temporal/evolution.py` |
| Change output adapter (Parquet → Postgres) | `run_day.py` → swap `SQLiteAdapter` for `PostgresAdapter` |

---

**Next:** Read `docs/05_Developer_Quick_Start.md` for the broader codebase tour
and `docs/03_Maintainer_Guide.md` before making structural changes.
