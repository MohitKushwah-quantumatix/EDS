# P007B — Destination Adapter Framework

**Status: proposed design, for architectural review. Nothing here is
implemented.**

**Governed by:** PADR-002 (platform-independent domains), PADR-003 (output
adapter isolation), PADR-007 (configuration ownership), PADR-013 (the scheduler
coordinates), PADR-015 (the runner is the runtime integration boundary),
PADR-016 (data is domain state).

**Read with [PADR-017](PADR-017-enterprise-distribution-architecture.md)**,
which extends this design from one destination to an enterprise topology and is
where the decision is recorded. Everything below stands; §17 says what changed.

---

## 1. Objectives

Deliver the datasets a simulation generates to any of several target systems,
**without changing the Platform, the Runner's responsibilities, or any Domain**.

Concretely:

* One generated enterprise, many destinations, chosen by configuration.
* A domain that has never heard of a destination and cannot be made to.
* Filesystem behaviour byte-identical to today, as the default.
* A new destination costs one package and one registration line.
* No plugin framework, no discovery, no reflection, no DI container.

### The finding that shapes everything below

There is already an adapter layer. `eds/adapters/` defines `DatasetWriter` and
`DatasetReader`, and `ParquetAdapter` implements both. The obvious design —
"make MSSQL another `DatasetWriter` and point the runner at it" — is wrong, and
it is worth being precise about why, because it is the design most reviewers
will arrive with.

**PADR-016 requires a readable store of record.** A domain derives its entire
state from persisted business data: whether it is founding or continuing, which
identifiers have been issued, what the business looks like now. The runner reads
that data back on every unit of work. So the write path is not a one-way pipe —
it is half of a read/write cycle that the simulation itself depends on.

Delivery destinations have no such obligation, and most of them cannot meet it.
A REST endpoint cannot be queried for last year's orders. A Kafka topic is not a
table. A warehouse *could* be read back, but at a latency and cost that would
make every simulated day a round trip to it.

Two conclusions follow:

1. **Delivery is one-way.** A `DeliveryTarget` writes and never reads. Requiring
   `read` of every target would make five of the six Phase 1 destinations
   unimplementable or absurd.
2. **Delivery is additive, not a substitution.** A run that delivers to MSSQL
   still maintains its store of record, because otherwise it loses the ability
   to continue — silently, and not until the second simulated day.

The naive design does not fail loudly. It produces a first day that looks
perfect and a second day that founds the enterprise again.

So:

| Package | Role | Direction | Governed by |
| --- | --- | --- | --- |
| `eds.adapters` | **Store of record** — the enterprise's own data | read **and** write | PADR-003 |
| `eds.delivery` | **Destinations** — where the data is *sent* | write only | this design |

Both write. Only the store of record is read. That is the distinction the new
package exists to make, and it is the answer to "why not just add adapters".

---

## 2. Design principles

1. **One-way.** A target accepts data. It never answers questions about data.
2. **No business logic in a target.** A target may know a table name, a batch
   size and a connection string. It may not know what a customer is.
3. **The runner is the only caller.** Nothing in `eds.platform` or
   `eds.domains` imports `eds.delivery`, enforced by test (PADR-015).
4. **Reuse before invention.** `WriteResult`, `eds.core.schema.Dataset` and the
   existing Parquet writer are used as they are. No new type is introduced that
   carries no new information.
5. **Explicit registration.** A target is registered by an import and a call,
   mirroring `register_domain` — a pattern already accepted in this codebase
   (PADR-006).
6. **Generalise from two, never from one.** No shared SQL base class until two
   SQL targets exist and the duplication is visible.
7. **The default changes nothing.** Absent configuration means filesystem,
   means today's bytes.

---

## 3. Package structure

```
eds/delivery/
├── __init__.py          Public surface: the protocol, the registry, the errors
├── base.py              DeliveryTarget, DatasetPackage, Disposition, DeliveryContext
├── errors.py            DeliveryError and its subclasses
├── registry.py          register_target, create_target, registered_targets
├── config.py            DeliverySettings and the per-kind settings models
└── targets/
    ├── __init__.py      Imports the built-in targets — the only registration point
    ├── filesystem.py    Wraps the existing Parquet writer. The default
    ├── postgresql.py    Phase 1
    ├── mssql.py         Phase 1
    ├── mysql.py         Phase 1
    ├── mongodb.py       Phase 1
    └── rest.py          Phase 1
```

Deliberately flat. There is no `sql/` subpackage and no `SqlTarget` base class in
this structure, because at design time there is nothing to share — only a
prediction that there will be. §16 says when to revisit that, and the answer is
"after the second SQL target, not before the first".

`eds/delivery/` may depend on `eds.core` (schemas, frames) and on
`eds.adapters` (the filesystem target reuses the Parquet writer). It may not
depend on `eds.platform`, `eds.domains` or `eds.runners`.

---

## 4. Component responsibilities

| Component | Owns | Never owns |
| --- | --- | --- |
| **`DeliveryTarget`** | Connecting, translating frames into the destination's shape, writing, reporting what landed | What the data means; whether it should have been sent; what happens if it fails |
| **Registry** | Name → factory. Which targets exist | Choosing one |
| **`DeliverySettings`** | What each configured target needs to reach its destination | Anything about a business |
| **`DatasetPackage`** | The unit of delivery: frames, their declarations, and how each should land | How to land it |
| **Runner** | Selecting the target, building the package, driving the lifecycle, classifying failures | How a target talks to its destination |
| **Platform** | Ordering, timing, state, results — unchanged | Delivery. It does not know the package exists |
| **Domain** | Generating data and declaring what it is — unchanged | Destinations, entirely |

Two placements deserve their reasons stated.

**The runner selects the target.** Choosing where data goes needs both
vocabularies: the platform's (which run, which project, which directory) and the
domain's (which datasets, what each one is). That is the definition of the
integration boundary (PADR-015). The scheduler must not choose, because it would
then be reasoning about destinations; the domain must not, because it would then
know destinations exist.

**The runner maps temporality to disposition.** A domain declares, per dataset,
whether it is static, append-only, a mutable snapshot or slowly changing
(ADR-014). A destination needs to know whether to replace, append or upsert.
These are two vocabularies for one fact, and translating between them is exactly
what the boundary is for:

| Domain says (ADR-014) | Delivery hears |
| --- | --- |
| `STATIC` | `REPLACE` — and only on the founding unit of work |
| `APPEND_ONLY` | `APPEND` |
| `MUTABLE_SNAPSHOT` | `REPLACE` |
| `SLOWLY_CHANGING` | `UPSERT` on the declared primary key |

The mapping lives in the runner. The domain never learns the word *disposition*;
no target ever learns the word *temporality*.

---

## 5. Adapter lifecycle

A target is opened once per run, delivered to once per stage per unit of work,
and closed once.

```
run begins
  │
  ├─ runner reads delivery settings, asks the registry for the target
  ├─ target.open(context)                      ← connect, authenticate, ensure schema
  │
  │   for each unit of work (business date):
  │     for each stage:
  │        ├─ domain generates
  │        ├─ runner writes the store of record        (eds.adapters, unchanged)
  │        ├─ runner builds a DatasetPackage
  │        └─ target.deliver(package) → receipts
  │
  ├─ target.close()                            ← flush, commit, disconnect
  │
run ends
```

**Why a lifecycle at all**, when the existing `DatasetWriter` is a single
method: a connection cannot be opened and torn down per dataset. A year of
Retail is 39 datasets × 365 days ≈ 14,000 deliveries; opening a database
connection or acquiring an OAuth token for each is not a performance concern, it
is a different design. The lifecycle is the minimum that makes a stateful
transport expressible, and the filesystem target simply implements `open` and
`close` as no-ops.

**`close` must run whether or not delivery succeeded.** A target that has
buffered rows and is never closed loses them, and the loss is invisible. The
runner owns that guarantee.

**Ordering is not the target's business.** Packages arrive in dependency order
because the plan already ordered the stages (PADR-008). A target that reordered
or deferred them would be scheduling.

---

## 6. Interface definitions

Signatures only, as a contract to review. No implementation.

```python
# eds/delivery/base.py


class Disposition(StrEnum):
    REPLACE = "replace"
    APPEND = "append"
    UPSERT = "upsert"


@dataclass(frozen=True, slots=True)
class DeliveryContext:
    """What a target may know about the run it is serving."""

    run_id: str
    project_id: str
    domain: str
    business_date: date


@dataclass(frozen=True, slots=True)
class DeliveredDataset:
    """One dataset, and how it should land."""

    name: str
    frame: pl.DataFrame
    declaration: Dataset  # eds.core.schema.Dataset — columns, PK, uniques, FKs
    disposition: Disposition


@dataclass(frozen=True, slots=True)
class DatasetPackage:
    """Everything produced by one stage on one business date."""

    stage: str
    business_date: date
    datasets: tuple[DeliveredDataset, ...]


@runtime_checkable
class DeliveryTarget(Protocol):
    @property
    def name(self) -> str: ...

    def open(self, context: DeliveryContext) -> None: ...

    def deliver(self, package: DatasetPackage) -> tuple[WriteResult, ...]: ...

    def close(self) -> None: ...
```

### Reuse of `WriteResult`

`deliver` returns the existing `eds.adapters.base.WriteResult` — `(dataset,
location, rows)` — rather than a new receipt type. `WriteResult`'s own docstring
already says `location` is "an identifier meaningful to the adapter — a file
path, a qualified table name, a topic". It was designed for this and a
`DeliveryReceipt` would carry no information it does not.

The one thing it cannot express is a *partial* delivery. §10 argues that partial
delivery should not be representable, which is why this is not treated as a gap.

### Why the declarations travel with the frames

A SQL target needs types, a primary key and unique constraints to create a
table. All of that is already declared in `eds.core.schema.Dataset`, so **no
target needs to infer a schema from a frame**, and two targets cannot infer
different schemas from the same data.

**Open question for review.** `Dataset` declares columns, primary key, unique
columns and foreign keys — but *not per-column nullability*. A SQL target
generating DDL would have to make every non-key column nullable, which is
weaker than the data actually is. Options: add nullability to `Dataset` (a
`core` change affecting all 39 declarations), infer it from the frame (two
targets could disagree), or accept nullable columns (honest, and loses a
constraint). **Recommendation: accept nullable columns in Phase 1 and raise
nullability as its own decision** — it is a change to the canonical business
model (PADR-001) and should not be smuggled in as a delivery detail.

---

## 7. Dataset package structure

The unit of delivery is **one stage's output for one business date**.

Not per dataset: a target would lose the ability to write related tables in one
transaction, and the number of round trips would rise by an order of magnitude.

Not per run: a run may be 365 days long. Buffering it would mean holding a year
of an enterprise in memory before anything was delivered, and a failure on day
360 would deliver nothing.

Per stage is also the granularity at which the platform already reports
(`StageResult`), which means delivery outcomes line up with execution outcomes
with no extra bookkeeping.

### Which frame goes in the package

The domain distinguishes what a unit of work *generated* from what the datasets
now *hold* — the increment and the whole. Today the runner writes the whole to
the store of record. Delivery should take whichever matches the disposition:

| Disposition | Frame delivered |
| --- | --- |
| `REPLACE` | The whole dataset as it now stands |
| `APPEND` | **The increment only** |
| `UPSERT` | The rows that changed, keyed by the declared primary key |

This matters more than it looks. Re-delivering an entire append-only history
every simulated day is O(history) per day — tolerable when the destination is a
local file, and unacceptable when it is a database over a network. Delivering
increments makes a long run linear rather than quadratic.

No domain change is required: both frames already exist at the point the runner
builds the package.

---

## 8. Registry design

```python
# eds/delivery/registry.py
type TargetFactory = Callable[[TargetSettings], DeliveryTarget]


def register_target(kind: str, factory: TargetFactory) -> None: ...
def create_target(kind: str, settings: TargetSettings) -> DeliveryTarget: ...
def registered_targets() -> tuple[str, ...]: ...
```

Registration is a call at module import, and the built-in targets are imported
explicitly by `eds/delivery/targets/__init__.py`. There is no entry-point scan,
no directory walk and no `importlib`.

This mirrors `eds.platform.domain`, where a domain announces itself and the
platform holds no list of domain names. The argument for it here is the same
argument PADR-006 already accepted, plus the one PADR-015 makes against
reflection: **a rule enforced by reading imports is only worth having while
imports are what the code uses.**

A factory rather than a class, because a target's construction differs by kind —
one takes a directory, another a DSN and a schema name, another a base URL and a
credential — and a common constructor signature would be a fiction.

**Registering an unknown kind, or creating one, raises.** A misspelled `kind` in
configuration must fail before a run starts, naming what is available. Silently
falling back to the filesystem would mean a run that reports success and
delivered nothing where it was asked.

---

## 9. Configuration model

`configs/delivery.yaml`, **optional**. Absent means filesystem, which means
today's behaviour, which is what preserves backward compatibility (PADR-005) —
the same argument that made `evolution.yaml` optional.

```yaml
# Where a run's data is sent. Absent entirely means: filesystem, as before.

# The enterprise's own readable copy. PADR-016 depends on this, so it is
# always maintained and is always a readable adapter.
store_of_record: filesystem

# Which configured targets a run delivers to, in order.
deliver_to: [filesystem]

targets:
  filesystem:
    kind: filesystem

  warehouse:
    kind: postgresql
    dsn_env: EDS_WAREHOUSE_DSN        # the variable's NAME, never its value
    schema: retail
    batch_rows: 50_000

  feed:
    kind: rest
    base_url: https://ingest.example.internal/v1
    token_env: EDS_FEED_TOKEN
    batch_rows: 1_000
```

Pydantic models in `eds/delivery/config.py`, following the house style —
frozen, `extra="forbid"`, one model per kind, discriminated on `kind`. A bad
configuration fails at load with a precise error rather than part-way through a
long run (PADR-007).

Three rules worth stating explicitly:

* **Secrets are named, never written.** Configuration carries the *name* of an
  environment variable. A DSN or token in a YAML file under version control is
  the most likely way this framework causes a real incident.
* **A credential must not be reachable through `repr`.** Frozen dataclasses and
  Pydantic models print their fields. Any settings model holding a resolved
  secret needs an explicit repr override, and a test.
* **`deliver_to` is a list.** Delivering to two destinations is a configuration
  change, not a code change. This costs nothing now and is the difference
  between "and also send it to the warehouse" being a line of YAML or a phase of
  work.

**Ownership.** Delivery settings are platform-level, not domain-level: they say
nothing about a business. They belong beside `simulation.yaml`, and no domain
configuration model references them (PADR-007).

---

## 10. Error handling strategy

```
DeliveryError(RuntimeError)
├── TargetNotRegisteredError      an unknown kind
├── TargetConfigurationError      settings that cannot describe a destination
├── TargetUnavailableError        cannot connect, authenticate or reach
└── DeliveryRejectedError         the destination refused the data
```

**Delivery raises; the runner classifies.** A target has no business knowing
about `FailureType`, and the runner already does exactly this translation for
`AdapterError` (PADR-015). Delivery failures classify as
`FailureType.PERSISTENCE`, with the target named in the message so that "which
of the three destinations failed" is answerable from the result alone.

**Fail fast within a package.** If dataset 12 of 39 cannot be delivered, the
stage fails. The alternative — carry on and report a partial success — produces a
destination in a state nobody can describe.

**No transaction guarantee across a package.** It cannot be offered uniformly:
a SQL target could wrap 39 tables in one transaction, MongoDB partly, REST and
Kafka not at all. Promising it would be a lie in half the implementations.

**Idempotency replaces it, and it is a requirement on implementers.** A target
must be safe to re-deliver the same `(dataset, business_date, disposition)`
twice. That is what makes fail-fast recoverable: the store of record is
authoritative, so a failed delivery is re-run rather than repaired. The
framework cannot enforce this — it is a line in the protocol's docstring and a
test each target owes — and pretending otherwise would be the weakest point of
this design. It is stated here as a known weakness rather than a guarantee.

**Retry, and where it may live.** PADR-013 forbade retries in the scheduler and
that stands. But a transport-level retry — a socket reset, a 503, a token
refresh — is a property of a *transport*, not of orchestration, and belongs
inside the target that owns the transport: bounded, configured, and never
re-running a stage. **Re-delivering a stage is orchestration and remains out of
scope**, exactly as recovery and rollback were in P006.

---

## 11. Logging strategy

Delivery is the first component in this system that talks to anything outside
the process, which makes it the first place where logs are the only evidence of
what happened.

* **Log at the boundary, once per dataset**: target name, dataset, disposition,
  row count, duration, and the returned location. Not per row, not per batch.
* **Never log data.** Not a row, not a sample, not a failing value. A synthetic
  enterprise is not sensitive, but a framework whose logging habit is "print the
  offending row" becomes dangerous the moment somebody points it at something
  real.
* **Never log a credential**, including inside a connection string, including
  inside an exception message. Redaction belongs at the point the secret is
  resolved, not at the point it is printed.
* **Summarise per run**: destinations, datasets, rows, failures. One block a
  reader can paste into an incident.
* **A target's own client library must not be allowed to log at its default
  level.** Database and HTTP clients are verbose and some of them log
  credentials. Configuring third-party loggers down is part of each target's
  responsibility.

The scheduler remains forbidden from importing `logging` (PADR-013). Delivery is
not the scheduler and this does not weaken that rule.

---

## 12. Migration strategy

Five steps, each independently reviewable, each leaving a working system.

**Step 0 — the package, unused.** Add `eds.delivery` with the protocol, the
registry, the errors, the configuration models and the filesystem target. Nothing
calls it. The filesystem target wraps the existing Parquet writer rather than
reimplementing it.
*Gate:* the suite passes unchanged; nothing imports the new package outside its
own tests.

**Step 1 — the runner writes through delivery.** The runner builds packages and
delivers them; the filesystem target is the default. The store of record
continues to be written exactly as it is today.
*Gate:* **39 datasets byte-identical to the pre-P007B baseline.** This is the
only acceptance criterion that matters at this step, and the digest comparison
already exists.

**Step 2 — one database target.** PostgreSQL first: the most standard SQL, the
cheapest to run in a container, the fewest vendor quirks. Write it against the
interface and **let it change the interface** if it must — this is the step where
the design is tested, and discovering the protocol is wrong here is the cheapest
it will ever be.
*Gate:* a full Retail run delivers to Postgres; row counts and primary keys
match the store of record; a multi-day run still continues correctly.
*Status: implemented.* `eds.adapters.postgres` (PADR-018). The interface did
not need to change — `DatasetWriter`/`DatasetReader` as specified in PADR-003
were sufficient. A full Retail run's Parquet output was written to Postgres and
re-read with row counts matching the store of record; primary-key and
foreign-key *enforcement* in the database itself was descoped rather than built
(tables are created from Polars' inferred schema, not from
`eds.core.schema.Dataset`'s declared keys) and remains open for a future step.

**Step 3 — the second and third SQL targets.** MSSQL and MySQL. Only now is
duplication visible, and only now should a shared SQL component be considered.
*Gate:* whatever is extracted is extracted from two working implementations, not
predicted from one.

**Step 4 — the two that stress the design.** MongoDB has no DDL and no schema to
create; REST has no transactions, needs batching and pagination, and is the only
target where the destination may reject a single record. These are the ones most
likely to reveal that `deliver` is the wrong shape, which is why they come last
rather than first.
*Gate:* neither required a change to the domain, and any change to the protocol
is documented as an amendment to PADR-017.

**Nothing is deprecated.** `eds/adapters/` stays, PADR-003 stands, the CLI keeps
its path. This framework adds a way to send data; it removes nothing.

---

## 13. Acceptance criteria

Structural, and testable:

1. No module under `eds/domains/` imports `eds.delivery`, at any depth.
2. No module under `eds/platform/` imports `eds.delivery`.
3. `eds/delivery/` imports nothing from `eds.platform`, `eds.domains` or
   `eds.runners`.
4. A target can be added by adding one module and one registration call, proven
   by a fake target in the test suite that requires no change to platform,
   runner or domain code.
5. No module under `eds/delivery/` references a domain concept — no dataset
   name, no business entity, no domain vocabulary.

Behavioural:

6. **Filesystem delivery is byte-identical** to the pre-P007B baseline, all 39
   datasets.
7. Absent `configs/delivery.yaml`, a run behaves exactly as it does today.
8. **A multi-day run delivering to a non-readable destination still continues
   correctly** — the store of record remains authoritative. *This is the most
   important test in the list: it is the one that fails if PADR-016 has been
   broken, and it fails on the second simulated day, not the first.*
9. A target that raises is reported as `FailureType.PERSISTENCE`, naming the
   target, and the run's result says which stage and which business date.
10. `close` is called after a failed delivery.
11. Delivering the same package twice leaves the destination in the same state
    as delivering it once, for every target.
12. An unknown `kind` in configuration fails before the first stage runs.
13. No credential appears in any log line, exception message or `repr`.
14. Delivering to two destinations is a configuration change only.

Non-goals, stated so that review can reject them explicitly: no schema
migration of existing tables, no change-data-capture, no streaming, no
back-pressure, no delivery of *historical* data already generated, no
cross-destination consistency.

---

## 14. Architecture diagrams

### Where delivery sits

```
                    ┌─────────────────────────────┐
                    │        eds.platform         │  plan, project, time,
                    │                             │  run, contracts, scheduler
                    └─────────────────────────────┘
                                   ▲
                                   │
                    ┌─────────────────────────────┐
                    │         eds.runners         │  the integration boundary
                    │   selects the target,       │  (PADR-015)
                    │   builds the package,       │
                    │   classifies failures       │
                    └──────┬────────────┬─────────┘
                           │            │
              ┌────────────┘            └────────────┐
              ▼                                      ▼
   ┌─────────────────────┐                ┌─────────────────────┐
   │    eds.domains      │                │    eds.delivery     │
   │  generates data,    │                │  one-way targets:   │
   │  declares what      │                │  fs, SQL, Mongo,    │
   │  it is              │                │  REST, …            │
   └─────────────────────┘                └─────────────────────┘
              │                                      │
              │            ┌─────────────────────┐   │
              └───────────▶│      eds.core       │◀──┘
                           │  schemas, frames    │
                           └─────────────────────┘

              ┌─────────────────────┐
              │    eds.adapters     │  the STORE OF RECORD — read and write
              │  (read + write)     │  PADR-016 depends on it being readable
              └─────────────────────┘
                           ▲
                           └──── read and written by eds.runners

   eds.domains ✗──▶ eds.delivery        a domain cannot reach a destination
   eds.platform ✗──▶ eds.delivery       the platform does not know they exist
```

### One stage, two writes

```
   domain generates
         │
         ├──────────────▶  store of record          (eds.adapters)
         │                 whole frames, readable
         │                 ── this is what the next
         │                    day reads back
         │
         └──────────────▶  DatasetPackage           (eds.delivery)
                           increment or whole,
                           by disposition
                                 │
                                 ├──▶ filesystem
                                 ├──▶ postgresql
                                 └──▶ rest
```

The two arrows are the whole design. The left one is the simulation's own
memory and is not optional. The right one is delivery, and there may be none of
it or several.

### Lifecycle

```
 runner                          target                     destination
   │                               │                             │
   │── create_target(kind, cfg) ──▶│                             │
   │── open(context) ─────────────▶│── connect / authenticate ──▶│
   │                               │── ensure schema ───────────▶│
   │                               │                             │
   │  ╔═ per business date ═══════════════════════════════════╗  │
   │  ║ per stage:                                            ║  │
   │──╫─ deliver(package) ────────▶│── write batches ─────────▶║──│
   │◀─╫─ receipts ─────────────────│                           ║  │
   │  ╚═══════════════════════════════════════════════════════╝  │
   │                               │                             │
   │── close() ───────────────────▶│── flush / commit / close ──▶│
```

---

## 15. Risks and trade-offs

**Two write paths double the I/O.** Every dataset is written to the store of
record and delivered. That is the price of PADR-016 and it is not avoidable
while a domain derives its state from what it persisted. It is also the reason
increments matter (§7): if delivery re-sent whole histories, the cost would be
quadratic rather than doubled.

**Six targets in one phase is too many, and I recommend cutting it.** Filesystem,
PostgreSQL and one non-SQL target (REST, as the least like the others) would
exercise every part of this design. MSSQL and MySQL after Postgres are largely
type-mapping and dialect work with little architectural content, and doing them
before the design has been tested by a second *kind* of destination means
generalising from three near-identical implementations. This is the largest
scope risk in the phase.

**Type mapping is the hidden body of work.** Polars dtypes → SQL types, per
vendor, with decimals, timestamps, and string lengths all differing. It carries
no architectural interest and will consume most of the effort. It should be
estimated separately from the framework, or it will be discovered as an overrun.

**Testing becomes an infrastructure problem.** Real database targets need
containers; the suite is already eight minutes. Recommendation: fakes for the
protocol's contract tests, containers for a small number of integration tests
marked `slow`, and the `slow` marker already exists for exactly this.

**Idempotency is a requirement, not a guarantee** (§10). A target that gets it
wrong produces duplicated business history in a destination while the store of
record stays clean — a divergence nothing in the framework can detect. The only
mitigation is a shared contract test suite that every target must pass, and that
should be built in Step 2, before there are five targets to retrofit.

**Nullability is under-declared** (§6). Accepting nullable columns is honest but
weakens the destination schema against what the data guarantees.

**The framework invites business logic.** "Only deliver orders over £100", "skip
the test customers", "rename this column for the warehouse" — every one of these
will be asked for, each is reasonable, and each belongs in a domain or in a
consumer, never in a target. §13 criterion 5 exists to make the violation
visible in review.

**`deliver_to` as a list defers a real question.** If two destinations are
configured and the second fails, the first has the data and the second does not.
This design fails the stage and relies on idempotent re-delivery. That is
adequate; it is not cross-destination consistency, and §13 lists that as a
non-goal so nobody assumes otherwise.

---

## 16. Implementation roadmap

| Step | Scope | Exit gate |
| --- | --- | --- |
| **0** | `eds.delivery` package: protocol, registry, errors, config, filesystem target wrapping the existing writer. Unused. | Suite unchanged; contract tests for the protocol exist against a fake target |
| **1** | Runner delivers through the framework; filesystem is the default | **39 datasets byte-identical**; delivery config absent behaves as today |
| **2** | PostgreSQL target; shared contract test suite every target must pass | A full Retail run delivers to Postgres; a multi-day run still continues; interface changes (if any) recorded |
| **3** | MSSQL and MySQL. *Only now* consider extracting shared SQL machinery | Extraction justified by two working implementations |
| **4** | REST target, then MongoDB — the two that most stress the protocol | No domain change; protocol amendments documented |
| **5** | PADR-017 amended with what steps 2–4 taught. Future targets (Delta, Iceberg, Kafka, Snowflake, BigQuery, Databricks, Fabric) need no framework change | A new target is one package and one registration line |

**Recommended for Phase 1: steps 0, 1, 2 and the REST half of step 4.** That
delivers filesystem, one SQL destination and one non-SQL destination — enough to
prove the framework, with the remaining SQL vendors as follow-on work whose
architectural risk is near zero once step 3's extraction question is answered on
evidence.

---

## 17. Where this decision is recorded

**Superseded in scope by
[PADR-017](PADR-017-enterprise-distribution-architecture.md).** This design
assumed a run had *a* destination. That assumption did not survive contact with
enterprise topology: a real enterprise distributes its data across many systems,
each owning part of it. PADR-017 covers both — the one-way premise below is
stated there as §3.1, because distribution cannot be understood without it.

The target protocol, registry, configuration model, error handling and lifecycle
in this document stand unchanged. What changes is that a *Distribution Engine*
sits between the runner and the targets, and the runner no longer names a target
directly.

The premise, as PADR-017 now records it:

>
> A domain derives its state from persisted business data (PADR-016), so the
> data a simulation writes for itself must remain readable. Delivery
> destinations carry no such obligation and mostly cannot meet it.
>
> Therefore `eds.adapters` remains the store of record — read and written, always
> maintained — and `eds.delivery` holds one-way targets. Delivery is additive: a
> run may deliver to none, one or several destinations, and does so *in addition
> to* maintaining its own readable copy. A destination may never be substituted
> for the store of record.
>
> The runner is the only caller of `eds.delivery`, selects the target, translates
> a domain's declared temporality into a delivery disposition, and classifies
> delivery failures. A target holds no business logic and answers no questions
> about data.

PADR-017 should be amended when steps 2 to 4 of §16 have taught it something.
