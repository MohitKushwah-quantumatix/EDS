# Enterprise Data Simulator — Documentation

**EDS v1.0 · Official documentation suite**

EDS generates synthetic enterprise datasets by simulating business events. At the
default scale one run produces 39 referentially consistent datasets containing
about 153,000 rows, deterministically, in under six seconds.

**v1.0 refers to the frozen architecture, not the distribution version, which is
`0.1.0`.**

---

## The five documents

| # | Document | Audience | Read it to |
| --- | --- | --- | --- |
| 1 | **[Handbook](01_Handbook.md)** | Everyone | Learn EDS from zero: concepts, installation, configuration, running, output, troubleshooting, glossary |
| 2 | **[Architecture Reference](02_Architecture_Reference.md)** | Architects, senior engineers | Understand the design and all seventeen platform decision records. Reference only |
| 3 | **[Maintainer Guide](03_Maintainer_Guide.md)** | Maintainers | Evolve EDS safely: add a domain, a dataset, configuration; testing, review and release |
| 4 | **[Package Reference](04_Package_Reference.md)** | Developers | Find a class, function, protocol or extension point |
| 5 | **[Developer Quick Start](05_Developer_Quick_Start.md)** | New developers | Be productive in under 30 minutes |

### Where to start

```
New to EDS?                    ──▶  Quick Start (5), then Handbook (1)
Evaluating EDS?                ──▶  Handbook §§1–5, then Architecture Reference §1
Reviewing the design?          ──▶  Architecture Reference (2)
About to change something?     ──▶  Maintainer Guide (3)
Looking for a specific name?   ──▶  Package Reference (4)
Something is broken?           ──▶  Handbook §17, Quick Start §9
```

---

## Supporting documentation

| Location | Contents |
| --- | --- |
| [`platform/`](platform/README.md) | Platform vision, layer architecture, roadmap, and PADR-001 to PADR-017 — the decisions governing where code may live and what may depend on what |
| [`architecture/`](architecture/README.md) | ADR-001 to ADR-014 — the Retail domain's business rules |
| [`features/`](features/) | One folder per feature: business context, prompt, review |

The two decision-record sets do not overlap. **PADRs** answer *where code is
allowed to live and what may depend on what*. **ADRs** answer *what the data
means*.

Two proposed designs are documented but **not implemented in EDS v1.0**:
[P007B Destination Adapter Framework](platform/P007B-destination-adapter-framework.md)
and [PADR-017 Enterprise Distribution Architecture](platform/PADR-017-enterprise-distribution-architecture.md).

---

## Conventions used throughout

**Terminology** is defined once, in the
[Handbook glossary](01_Handbook.md#19-glossary), and used unchanged in all five
documents.

**Unimplemented functionality** is marked **"Not implemented in EDS v1.0"**. No
document describes behaviour the repository does not have.

**Measurements are measured.** Row counts, timings and file sizes come from real
runs at seed 42, not from estimates.

---

## What EDS v1.0 does not include

Stated once, here, and cross-referenced rather than repeated.

| Not implemented in EDS v1.0 | Where it is discussed |
| --- | --- |
| Logging — the config file exists; nothing reads it or emits records | [Handbook §13](01_Handbook.md#13-logs) |
| A CLI for projects, multi-day runs or resuming | [Handbook §11](01_Handbook.md#11-running-the-simulator) |
| Output to anything but Parquet | [Handbook §12.1](01_Handbook.md#121-a-cli-run) |
| Delivery to databases or APIs | [P007B](platform/P007B-destination-adapter-framework.md), [PADR-017](platform/PADR-017-enterprise-distribution-architecture.md) |
| Any domain other than Retail | [Maintainer Guide §3](03_Maintainer_Guide.md#3-how-to-add-a-domain) |
| Carrying a project forward across separate runs | [Package Reference — `eds.platform.run`](04_Package_Reference.md#edsplatformrun) |
| Retries, recovery, rollback, restart | [Architecture Reference — PADR-013](02_Architecture_Reference.md#padr-013--the-scheduler-coordinates-and-the-executor-arrives-as-an-argument) |
| Parallel execution | [Maintainer Guide §9](03_Maintainer_Guide.md#9-performance-expectations) |
| Growth engine, snapshots, SCD, CDC | [Maintainer Guide §6](03_Maintainer_Guide.md#6-how-to-extend-simulation) |
| Externally supplied domain inputs | [Package Reference — `eds.platform.execution`](04_Package_Reference.md#edsplatformexecution) |
| Per-column nullability in `Dataset` | [Package Reference — `eds.core`](04_Package_Reference.md#edscore) |
| Reserved packages: `eds/events/`, `eds/simulation/`, `eds/state/`, `eds/workflows/`, `eds/exporters/{csv,delta,sql}/`, `eds/platform/state.py` | [Package Reference — Reserved packages](04_Package_Reference.md#reserved-packages) |
| CI configuration, `CONTRIBUTING.md`, `CHANGELOG.md`, pre-commit, `Makefile` | [Maintainer Guide §12](03_Maintainer_Guide.md#12-release-checklist) |

---

## Verification baseline

Every figure quoted in this suite was measured on the repository at the time of
writing.

| Measurement | Value |
| --- | --- |
| Datasets generated | 39 |
| Rows at default scale (seed 42) | 152,890 |
| Output size | 4.1 MB |
| Full CLI generation | 5.7 s |
| Test suite | 2,413 passed, 1 deselected, 8 min 07 s |
| `pytest -m slow` (365 simulated days) | 1 passed, 5 min 48 s |
| Lint / format | Clean, 440 files |
| Types | Clean, 365 source files |
| Determinism | 39/39 files byte-identical to the pre-platform baseline |
