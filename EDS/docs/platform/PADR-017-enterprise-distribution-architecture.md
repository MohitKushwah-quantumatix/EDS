# PADR-017: Enterprise Distribution Architecture

**Status: Proposed. Design for architectural review — nothing here is
implemented.** To be marked Accepted on approval.

**Builds on:** PADR-003 (output adapter isolation), PADR-008 (the execution
model plans, it does not execute), PADR-013 (the scheduler coordinates),
PADR-015 (the runner is the runtime integration boundary), PADR-016 (data is
domain state), and the P007B design
([Destination Adapter Framework](P007B-destination-adapter-framework.md)).

**Numbering note.** The P007B design reserved PADR-017 for a narrower decision
— *delivery is one-way and the store of record is not a destination*. That
premise is now stated here, as §3.1, because a reader cannot understand
distribution without it and two records would have to be read in order anyway.
PADR-017 therefore covers both. P007B's §17 should be amended to point here.

---

## 1. Problem statement

The P007B design answered one question: **how does a dataset reach a
destination?** It assumed a run had *a* destination — one target, or a short list
of targets each receiving everything.

That assumption does not describe an enterprise.

A real on-premise enterprise has no single database holding its business. It has
an ERP that owns orders and inventory, a CRM that owns customers, a commerce
platform that owns carts and sessions, a warehouse management system that owns
shipments, a payment provider reached over HTTP, and an analytics estate that
receives copies of most of it. Each runs on different technology, each is owned
by a different team, and **none of them holds the whole picture**.

That topology is not incidental detail. It is the thing that makes enterprise
data integration hard, and it is therefore the thing anyone testing an
integration, a migration, a master-data-management tool or a reporting layer
most needs to simulate. A simulator that emits thirty-nine referentially perfect
tables into one schema produces data no enterprise has ever had.

So the problem is not delivery. It is **topology**: which business capability
owns which data, where that capability's data lives, and what the seams between
them look like.

Three consequences fall out immediately, and they shape the whole design.

**Ownership is not a property of a dataset.** Customer data lives in the CRM at
one company and in the ERP at another. Whether `customers` belongs to the CRM is
a fact about *an enterprise*, not about customers. So it cannot be declared by
the domain, and the constraint that the Retail domain stays unaware of
enterprise systems is not merely a layering rule — it is the only correct
modelling.

**Distribution breaks referential integrity, deliberately.** `orders.customer_id`
references `customers.customer_id`. Send orders to SQL Server and customers to
PostgreSQL and that foreign key crosses a system boundary, where no database can
enforce it. **That is what a real enterprise looks like**, and reproducing it is
the point. But it has to be *chosen and visible*, not discovered by somebody
whose load failed at three in the morning.

**The store of record becomes more important, not less.** Once no destination
holds everything, the only complete, readable, referentially closed copy of the
enterprise is the simulator's own (PADR-016). It stops being a convenience and
becomes the only place the simulation can continue from.

---

## 2. Design principles

1. **Topology is configuration, never code.** Changing which system owns which
   dataset is a YAML edit. It touches no Python.
2. **Topology is not a domain concern.** A domain declares what data *is*. An
   enterprise decides where it *lives*. The two never meet.
3. **One owner per dataset.** Every dataset has exactly one system of record
   inside the simulated enterprise. Copies are modelled as copies, explicitly.
4. **Seams are computed and reported, not discovered.** A profile that splits a
   foreign key says so at validation time.
5. **Validate before executing.** A topology that cannot be satisfied fails
   before the first stage runs, not on dataset 31 of 39.
6. **The store of record is not an enterprise system.** It is the simulator's
   memory. Conflating them is the central trap of this design (§3.5).
7. **A target does not know it is part of a topology.** Distribution is composed
   above delivery, not built into it.
8. **Additive, always.** Distribution adds destinations. It removes nothing and
   substitutes for nothing.
9. **Explicit registration and explicit assignment.** No discovery, no
   reflection, no wildcards where a mistake would be silent.

---

## 3. Core concepts

Five, and they are deliberately layered so that each knows less than the one
above it.

### 3.1 Premise: delivery is one-way and additive

Restated from P007B because everything here rests on it.

A domain derives its entire state from persisted business data (PADR-016) — so
the data a simulation writes for *itself* must remain readable. Delivery
destinations carry no such obligation and mostly cannot meet it: a REST endpoint
cannot be queried for last year's orders.

Therefore `eds.adapters` remains the **store of record**, read and written and
always maintained; `eds.delivery` holds **one-way targets**; and **a destination
may never be substituted for the store of record.** A run may distribute to
none, one or twelve systems, and does so *in addition to* maintaining its own
complete copy.

### 3.2 Enterprise System

**An Enterprise System is a named business capability with a home.**

It is not a database. It is the thing a database serves: "the ERP", "the CRM",
"Payments". It has three parts, and keeping them separate is what makes the model
useful:

| Part | What it says | Whose decision |
| --- | --- | --- |
| **Identity** | `erp`, `crm`, `payments` — a capability in this enterprise | Enterprise architecture |
| **Scope** | Which datasets it owns, and which it merely receives | Enterprise architecture |
| **Binding** | Which delivery target reaches it | Deployment |

The split between scope and binding is what lets one topology run against
containers in development and against real systems in production. The ERP owns
orders in both; it is a PostgreSQL container in one and SQL Server in the other.
Nothing about the topology changes.

An Enterprise System holds no business logic, no transport and no schema
knowledge. It is a name, a set of datasets, and a pointer to a target.

### 3.3 Ownership and subscription

The distinction that makes the model honest.

* **Ownership** — this system is the system of record for this dataset inside
  the simulated enterprise. **Exactly one system owns each dataset.**
* **Subscription** — this system receives a copy of a dataset it does not own.
  Any number of systems may subscribe to any dataset.

Real enterprises look exactly like this. Orders are *owned* by the ERP; the
analytics estate has a *copy*; the CRM has a *copy* of the ones its account
managers care about. Without the distinction, the "Analytics receives everything"
case would either be forbidden (uniqueness violated) or would make ownership
meaningless.

Ownership is what a consumer needs to know to answer "where is the truth?", and
it is what makes the seam report (§3.4) computable.

### 3.4 The seam report

A **seam** is a foreign key whose two ends are owned by different Enterprise
Systems.

`eds.core.schema.Dataset` already declares every foreign key, so seams are
derivable from a profile with no new declaration anywhere. For each profile the
engine can state, before anything runs:

```
Seams implied by profile 'distributed' — 14 cross-system references

  orders.customer_id        erp        →  crm         customers.customer_id
  orders.session_id         erp        →  commerce    sessions.session_id
  payments.order_id         payments   →  erp         orders.order_id
  shipments.payment_id      wms        →  payments    payments.payment_id
  ...
```

This is the most valuable artefact in the design and the cheapest to produce. It
turns the consequence of a topology into a document a reviewer can argue with:
*should* payments really be reachable only by an order identifier the payment
system cannot resolve? Sometimes yes — that is the integration problem being
simulated. Sometimes it means the topology is wrong.

It also has a hard technical consequence. A SQL target generating DDL must emit
foreign-key constraints for *local* references and **must not** for cross-system
ones, which would fail at load. So the seam analysis is not documentation only —
it feeds what a target is allowed to declare.

### 3.5 Distribution Profile

**A Distribution Profile is one complete enterprise topology: the set of
Enterprise Systems, what each owns, what each subscribes to, and what each is
bound to.**

Profiles are named and swappable. A repository is expected to hold several:

* `monolith` — one system owning everything. The degenerate case, and the one
  that must produce today's behaviour.
* `distributed` — the six-system topology in the problem statement.
* `customer-x` — a topology copied from an actual enterprise being modelled.

Swapping profiles changes where thirty-nine datasets land and changes nothing
else. **That is the answer to "how are different topologies supported without
changing the Retail domain":** the domain is not involved, because a profile is
not made of domain concepts. It is made of dataset *names* and system names, and
a dataset name is already public (the domain publishes it to the platform).

### The trap: the store of record is not a system

In the problem statement, *Analytics → Parquet* looks identical to the store of
record. It is not, and treating it as one is the mistake this design most needs
to prevent.

| | Store of record | Analytics system |
| --- | --- | --- |
| Purpose | The simulation's own memory | A modelled enterprise capability |
| Contents | All 39 datasets, always | Whatever the profile gives it |
| Read by | The runner, every unit of work | Nobody in the simulator |
| Governed by | PADR-016 | This record |
| Location | The project's data directory | Somewhere else entirely |

They must be different locations. Point an Analytics filesystem target at the
project's data directory and a partial view overwrites the simulator's complete
one — and the run continues, wrongly, from the following simulated day. **A
validation rule should refuse a target bound to the store of record's location.**

---

## 4. Architecture diagrams

### Where distribution sits

```
              ┌────────────────────────────────────┐
              │            eds.platform            │  unchanged
              │  plan · project · time · run ·     │  knows nothing of
              │  contracts · scheduler             │  systems or targets
              └────────────────────────────────────┘
                                ▲
                                │
              ┌────────────────────────────────────┐
              │            eds.runners             │  the integration
              │  builds ONE package per stage      │  boundary (PADR-015)
              │  writes the store of record        │  knows no topology
              └───────┬──────────────────┬─────────┘
                      │                  │
        ┌─────────────┘                  └──────────────┐
        ▼                                               ▼
┌──────────────────┐                    ┌──────────────────────────────┐
│   eds.domains    │                    │        eds.delivery          │
│  generates data, │                    │                              │
│  declares what   │                    │  ┌────────────────────────┐  │
│  it is           │                    │  │  Distribution Engine   │  │
│                  │                    │  │  resolves the profile, │  │
│  knows no        │                    │  │  splits the package,   │  │
│  destination and │                    │  │  drives the fan-out    │  │
│  no system       │                    │  └───────────┬────────────┘  │
└──────────────────┘                    │              │ sub-packages  │
        │                               │      ┌───────┴───────┐       │
        │                               │      ▼       ▼       ▼       │
        │                               │   target  target  target     │
        │                               │   (knows nothing of systems) │
        │                               └──────────────────────────────┘
        │                                               │
        │        ┌──────────────────┐                    │
        └───────▶│     eds.core     │◀───────────────────┘
                 │ schemas · frames │
                 └──────────────────┘

        ┌────────────────────────────────┐
        │         eds.adapters           │  STORE OF RECORD
        │       read  +  write           │  all 39 datasets, always,
        └────────────────────────────────┘  readable — PADR-016
                         ▲
                         └── read and written by eds.runners
```

Each layer knows strictly less than the one above: **the runner knows no
topology, the engine knows no business, the target knows no enterprise.**

### One stage, one package, many systems

```
                       domain generates
                              │
        ┌─────────────────────┴─────────────────────┐
        ▼                                           ▼
  store of record                          DatasetPackage
  all datasets                             (one stage, one date)
  whole frames                                     │
  readable                                         ▼
  ── the simulation's                      ┌───────────────┐
     own memory                            │ Distribution  │
     NOT a destination                     │    Engine     │
                                           └───────┬───────┘
                              ┌────────────────────┼────────────────────┐
                              ▼                    ▼                    ▼
                        ┌───────────┐        ┌───────────┐        ┌───────────┐
                        │    erp    │        │    crm    │        │ analytics │
                        │  owns 11  │        │  owns 4   │        │  owns 0   │
                        │  ──────── │        │  ──────── │        │ subs ALL  │
                        │  mssql    │        │ postgres  │        │  parquet  │
                        └───────────┘        └───────────┘        └───────────┘
                              │                    │                    │
                    orders, order_lines,     customers,           every dataset
                    inventory, …             addresses, …         this stage made
```

### The seam a topology creates

```
        ERP (SQL Server)                      CRM (PostgreSQL)
   ┌────────────────────────┐            ┌────────────────────────┐
   │ orders                 │            │ customers              │
   │   order_id      PK ────┼── local ──▶│                        │
   │   customer_id   FK ────┼┄┄┄┄┄┄┄┄┄┄┄▶│   customer_id     PK   │
   │ order_lines            │   SEAM     │ customer_addresses     │
   │   order_id      FK ────┘  (not      │                        │
   └────────────────────────┘ enforceable)└────────────────────────┘

   ── local FK   → emitted as a database constraint
   ┄┄ seam       → no constraint; reported by the engine; the integration
                   problem being simulated
```

---

## 5. Component responsibilities

| Component | Owns | Never owns |
| --- | --- | --- |
| **Domain** | Generating data; declaring what each dataset is — **unchanged** | Systems, targets, topologies, destinations |
| **Runner** | Building one package per stage; writing the store of record; handing the package to the engine; classifying failures | Which systems exist; which dataset goes where; how a target works |
| **Distribution Engine** | Resolving and validating a profile; computing seams; splitting one package into per-system sub-packages; driving target lifecycles; aggregating outcomes | Business meaning; transport; scheduling; what a dataset *is* |
| **Enterprise System** | A name, a scope, a binding | Behaviour of any kind — it is a value, not a component |
| **Delivery Target** | Connecting; writing; reporting what landed — **unchanged from P007B** | That a topology exists; that other targets exist |
| **Store of record** | The complete readable copy the simulation continues from | Being a destination |
| **Platform** | Ordering, timing, state, results — **unchanged** | All of the above. It does not know distribution exists |

Three placements need their reasons stated.

**The engine lives in `eds.delivery`, not in the runner.** It needs dataset
names, schema declarations, a profile and a set of targets — and *none* of the
platform's or the domain's vocabulary. Putting it in the runner would grow the
integration boundary, and PADR-015 says explicitly that growth of the runner is
an architectural signal requiring review. Routing is not translation.

**The runner still builds exactly one package per stage.** It does not split. If
it split, it would have to know the topology, and then the boundary would hold
enterprise architecture. It hands over a complete package and receives a
complete set of outcomes.

**A target never learns it received a subset.** It is handed datasets and a
disposition. Whether those datasets are all of a stage's output or four of
nineteen is not a question a target can usefully ask, and letting it ask would
put topology into every target.

---

## 6. Distribution profiles

A profile is a value, validated on load, and the validation is where this design
pays for itself.

### Validation rules

Checked once, before the first stage runs:

1. **Total assignment.** Every dataset the domain declares is owned by exactly
   one system — or falls through to a declared `default_system`. Unassigned and
   no default is an error.
2. **Unique ownership.** No dataset is owned twice. Two systems of record for one
   entity is a topology bug, not a topology.
3. **No phantom datasets.** No system owns or subscribes to a name the domain
   does not produce. *This is the rule that earns the most.* A renamed dataset
   otherwise silently stops being delivered, and nothing fails.
4. **Bindings resolve.** Every system's `target` names a configured delivery
   target (P007B §9).
5. **No collision with the store of record.** No target is bound to the
   project's data directory (§3.5).
6. **Redundant subscription.** A system subscribing to what it owns is a warning,
   not an error — harmless, but a sign the profile is being edited without being
   understood.
7. **Names are unique** and stable enough to appear in a log.

### What validation produces

Not a boolean. A **distribution report**, emitted at run start and worth keeping
with the run's results:

```
Profile 'distributed' — 6 systems, 39 datasets

  erp        mssql       owns 11   subscribes 0    orders, order_lines, …
  crm        postgres    owns  4   subscribes 0    customers, …
  commerce   mongodb     owns 12   subscribes 0    sessions, shopping_carts, …
  wms        mysql       owns  8   subscribes 0    shipments, inventory, …
  payments   rest        owns  4   subscribes 0    payments, …
  analytics  parquet     owns  0   subscribes 39   (all)

  Seams: 14 cross-system foreign keys  (listed above)
  Store of record: complete, 39 datasets, referentially closed
```

The last line matters. It is the standing reminder that however fragmented the
delivered picture is, one complete one exists.

### The degenerate profile

A profile with one system owning everything must reproduce today's behaviour
exactly. It is the migration path (§10) and a permanent test: **if the
`monolith` profile ever stops producing byte-identical output, distribution has
acquired behaviour it should not have.**

---

## 7. Enterprise system model

Shapes only, for review. No implementation.

```python
# eds/delivery/distribution.py


@dataclass(frozen=True, slots=True)
class EnterpriseSystem:
    """A business capability with a home."""

    name: str  # 'erp', 'crm', 'payments'
    target: str  # a configured delivery target's name
    owns: tuple[str, ...]  # datasets this system is the record for
    subscribes: tuple[str, ...]  # copies it also receives


@dataclass(frozen=True, slots=True)
class Seam:
    """A foreign key whose ends live in different systems."""

    dataset: str
    column: str
    owner: str  # system owning `dataset`
    references: str
    referenced_owner: str  # system owning `references`


@dataclass(frozen=True, slots=True)
class DistributionProfile:
    """One complete enterprise topology."""

    name: str
    systems: tuple[EnterpriseSystem, ...]
    default_system: str | None

    def owner_of(self, dataset: str) -> str: ...
    def recipients_of(self, dataset: str) -> tuple[str, ...]: ...
    def seams(self, declarations: Mapping[str, Dataset]) -> tuple[Seam, ...]: ...
    def validate(self, declared: Iterable[str]) -> list[ProfileIssue]: ...
```

The engine itself is one object with the lifecycle P007B defined, one layer up:

```python
class DistributionEngine:
    """Splits one stage's package across a topology."""

    def open(self, context: DeliveryContext) -> None: ...
    def distribute(self, package: DatasetPackage) -> tuple[SystemOutcome, ...]: ...
    def close(self) -> None: ...
```

`SystemOutcome` carries the system name and the receipts its target returned, so
"which system got what" is answerable from a run's result without inspecting any
destination.

Note what is absent: no base class for systems, no visitor, no strategy object,
no routing DSL. A profile is data; the engine is a loop over it.

---

## 8. Configuration model

Two files, because they answer different questions and change on different
schedules.

**`configs/delivery.yaml`** — *how to reach things.* Unchanged from P007B:
targets, credentials by environment-variable name, batch sizes. Changes when
infrastructure changes.

**`configs/enterprise.yaml`** — *what the enterprise looks like.* New. Changes
when the modelled topology changes, which is a different decision made by
different people.

```yaml
# configs/enterprise.yaml
#
# Enterprise topology. Absent entirely means: one system, everything, the
# store of record's format — which is today's behaviour.

active_profile: distributed

profiles:

  # The degenerate case. Must remain byte-identical to pre-distribution output.
  monolith:
    default_system: warehouse
    systems:
      warehouse:
        target: local_files

  distributed:
    systems:
      erp:
        target: erp_mssql
        owns: [orders, order_lines, order_status_history, inventory,
               products, categories, brands, suppliers, warehouses,
               tax_codes, coupon_types]

      crm:
        target: crm_postgres
        owns: [customers, customer_addresses, customer_preferences,
               customer_loyalty]

      commerce:
        target: commerce_mongo
        owns: [sessions, customer_personas, category_views, search_history,
               product_views, wishlists, shopping_carts, cart_items,
               checkout, payment_methods, shipping_methods, return_reasons]

      wms:
        target: wms_mysql
        owns: [shipments, shipment_items, shipment_status_history,
               returns, return_items, return_status_history,
               countries, states, cities]

      payments:
        target: payments_api
        owns: [payments, payment_status_history, reviews, order_status_history]

      analytics:
        target: analytics_files
        owns: []
        subscribes: ALL
```

### Rules the shape enforces

* **`owns` is enumerated, never a pattern.** A wildcard that silently stops
  matching a renamed dataset is the failure mode this design most wants to
  prevent, and validation rule 3 only works against explicit names.
* **`subscribes: ALL` is a keyword, not a pattern.** "Everything" is unambiguous
  and cannot drift; `order*` can.
* **`default_system` is the escape hatch**, and the distribution report always
  names what fell through it. Recommended for `monolith`, discouraged for
  production topologies, where being explicit is the point.
* **Absent file means one system, everything, as before.** Backward
  compatibility by the same argument that made `evolution.yaml` optional
  (PADR-005).
* **No credentials here.** They stay in `delivery.yaml`, referenced by
  environment-variable name. A topology file should be safe to share with the
  people who argue about topology.

### Ownership is a modelling decision, and the framework cannot make it

The assignment above is *an* answer, not *the* answer. Whether `reviews` belongs
to Commerce or to a separate content system, whether geography is master data in
the ERP or reference data in the WMS — these are enterprise architecture
questions with different answers at different companies. The framework's job is
to make the decision explicit, checkable and swappable. It is not to have an
opinion.

---

## 9. Sequence diagrams

### Run start: resolve, validate, refuse early

```
 runner            engine          profile        registry        targets
   │                 │                │              │               │
   │─ open(ctx) ────▶│                │              │               │
   │                 │─ load ────────▶│              │               │
   │                 │─ validate(declared datasets) ─┤               │
   │                 │◀─ issues ──────│              │               │
   │                 │                                               │
   │                 │  ── any issue: raise, before any stage runs ── │
   │                 │                                               │
   │                 │─ seams(declarations) ─────────┤               │
   │                 │─ report topology + seams ──── (log / result)  │
   │                 │                                               │
   │                 │─ create_target(kind, cfg) per system ────────▶│
   │                 │─ open(ctx) per target ───────────────────────▶│
   │◀─ ready ────────│                                               │
```

Failing here is the whole point. A misspelled dataset name, an unbound system or
a target pointed at the store of record must stop a run before it has generated
anything.

### Per stage: one package in, many sub-packages out

```
 domain          runner              engine                    targets
   │               │                   │                          │
   │─ generated ──▶│                   │                          │
   │               │─ store of record ─┼─────────────────▶ (eds.adapters)
   │               │                   │                          │
   │               │─ package ────────▶│                          │
   │               │                   │ for each system:         │
   │               │                   │   subset = owns ∪ subs   │
   │               │                   │   skip if empty          │
   │               │                   │─ deliver(sub) ──────────▶│
   │               │                   │◀─ receipts ──────────────│
   │               │◀─ outcomes ───────│                          │
   │               │                                              │
   │               │  ── any failure: classify PERSISTENCE,        │
   │               │     naming the system and the target ──       │
```

A system whose subset is empty for this stage is skipped, not called with
nothing. The CRM has no part in the commerce stage, and a target that receives
an empty package cannot tell "nothing for you" from "a bug upstream".

### Run end

```
   │─ close() ─────▶│─ close() per target ────────────▶│
   │                │  ── every target, even after a failure ──
   │◀─ summary ─────│
```

---

## 10. Migration strategy

Six steps. Each leaves a working system, and the first three need no database at
all.

**Step 0 — the model, unused.** `EnterpriseSystem`, `DistributionProfile`,
validation, seam computation, the report. No engine, no wiring. A profile can be
loaded, validated and described.
*Gate:* the `distributed` profile above validates against Retail's 39 datasets
and prints its seams. Nothing else in the system changed.

**Step 1 — the monolith profile through the engine.** One system, everything,
bound to a filesystem target. The runner hands packages to the engine instead of
to a single target.
*Gate:* **39 datasets byte-identical to the pre-distribution baseline.**

**Step 2 — two systems, both filesystem, different directories.** The cheapest
and most important step in the plan: it proves the entire distribution mechanism
— splitting, ownership, subscription, fan-out, per-system outcomes — with no
database, no container and no network.
*Gate:* the **union of the two directories equals the store of record**, dataset
for dataset and row for row; the seam report lists exactly the foreign keys that
cross the two.

**Step 3 — heterogeneous, two kinds.** One SQL system and one file system. This
is where "a target does not know it is part of a topology" is tested, and where a
SQL target must first honour the local-versus-seam distinction in its DDL.
*Gate:* the SQL system declares constraints for local foreign keys and none for
seams; a multi-day run still continues from the store of record.

**Step 4 — the full six-system topology.** ERP, CRM, Commerce, WMS, Payments,
Analytics.
*Gate:* no domain change was required at any point; the distribution report
matches the intended architecture.

**Step 5 — a second topology.** A profile with a materially different ownership
split, to prove that swapping topologies is configuration.
*Gate:* both profiles run against the same project, changing only which
destination holds what.

**Nothing is deprecated.** `eds.adapters` unchanged, PADR-003 stands, P007B's
target protocol unchanged, the CLI untouched, the Retail domain untouched.

---

## 11. Risks and trade-offs

**Delivered data is not referentially closed, by design.** This is the feature
and the largest risk together. A consumer joining across two systems will find
dangling keys — correctly — and will report it as a bug. The mitigations are the
seam report, the store of record, and documentation that says plainly which
copy is closed and which is not.

**Ownership assignments will be argued about, and the framework cannot settle
them.** Expect the first serious topology to take longer to agree than to
implement. That is a healthy sign — it means the model is describing something
real — but it should be planned for rather than discovered.

**Fan-out multiplies I/O.** An analytics system subscribing to everything doubles
delivery on its own; the store of record is a third copy. Increment delivery
(P007B §7) is what keeps this linear rather than quadratic, and it stops being an
optimisation and becomes a requirement at this scale.

**Partial success is now worse than in P007B.** ERP accepted, CRM refused: one
destination holds a business day the other does not. There is no distributed
transaction here and there will not be one. The stance: fail the stage, report
per system so re-delivery can be targeted, and rely on target idempotency —
which remains a requirement on implementers rather than a guarantee, and is the
weakest joint in the whole design.

**Profiles drift as domains evolve.** A dataset added by a future feature is
unowned, and the profile silently becomes incomplete. Validation catches it, but
only if validation runs. **Recommendation: validate every shipped profile against
every registered domain in the test suite**, so drift fails in CI rather than in
an operator's console.

**The store-of-record collision is a real hazard** (§3.5). One misconfigured path
turns a partial view into the simulation's memory, and the damage appears a day
later. Validation rule 5 exists for this and should be treated as a safety
control rather than a nicety.

**Testing surface grows sharply.** Six systems across five technologies means
containers, credentials and fixtures. Steps 0 to 2 need none of it, which is
deliberate: most of the architectural risk can be retired before any
infrastructure exists.

**More concepts.** System, profile, ownership, subscription, seam, binding. That
is six new nouns, and the honest defence is not that they are few but that each
one names something an enterprise architect already says out loud. A design with
fewer nouns would be encoding the same distinctions implicitly.

---

## 12. Acceptance criteria

**Structural**

1. No module under `eds/domains/` imports `eds.delivery`, at any depth.
2. No module under `eds/platform/` imports `eds.delivery`.
3. `eds/delivery/` imports nothing from `eds.platform`, `eds.domains` or
   `eds.runners`.
4. No module under `eds/delivery/` names a business entity or a specific dataset.
   Topology lives in configuration; dataset names reach the engine as data.
5. A delivery target contains no reference to systems, profiles, ownership or
   seams.
6. The runner contains no reference to any system name.

**Profile correctness**

7. A profile leaving a dataset unowned, with no default, fails validation.
8. A profile owning a dataset twice fails validation.
9. A profile naming a dataset the domain does not produce fails validation.
10. A profile naming an unconfigured target fails validation.
11. A profile binding a target to the project's data directory fails validation.
12. Every profile shipped in `configs/` validates against every registered
    domain, **as a test**.
13. Validation failures are reported together, before the first stage runs.

**Behavioural**

14. The `monolith` profile produces output **byte-identical** to the
    pre-distribution baseline.
15. Absent `configs/enterprise.yaml`, a run behaves exactly as it does today.
16. For a two-system filesystem profile, the **union of the destinations equals
    the store of record**, dataset for dataset and row for row.
17. **A multi-day run distributed across systems still continues correctly** —
    the store of record remains complete and authoritative. *The most important
    criterion here: it is what fails if PADR-016 has been broken, and it fails on
    the second simulated day, not the first.*
18. The seam report for a given profile is deterministic and complete: every
    cross-system foreign key, no others.
19. A SQL system emits constraints for local foreign keys and none for seams.
20. A system with nothing to receive for a stage is not called.
21. A failure in one system is reported as `FailureType.PERSISTENCE`, naming the
    system, the target, the stage and the business date.
22. Every target is closed even when another system's delivery failed.
23. Distributing the same package twice leaves every destination as it was after
    once.
24. Swapping `active_profile` changes only where data lands.

**Non-goals**, stated so review can reject them explicitly: no distributed
transactions; no cross-system consistency guarantee; no schema migration of
existing enterprise systems; no change-data-capture; no reconciliation tooling;
no streaming or back-pressure; no redistribution of data generated before a
profile existed.

---

## What this decision would not permit

* A domain may not name an enterprise system, a profile, or a target — nor gain
  a declaration from which one could be inferred.
* A delivery target may not learn that a topology exists.
* The platform may not learn that distribution exists.
* No dataset may have two owners; a copy is a subscription and is written as one.
* No destination may be substituted for the store of record, and no target may be
  bound to its location.
* Topology may not be expressed in code. If a decision about which system owns
  what is being made in Python, it is in the wrong place.
