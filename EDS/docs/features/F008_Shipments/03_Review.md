# F008 - Review

| Field | Value |
| --- | --- |
| Outcome | Complete; all three volume targets met |
| Environment | Windows 10, Python 3.13.0 |
| Verified | `pytest`, `ruff check .`, `ruff format --check .`, `mypy eds`, end-to-end CLI run |

## Acceptance criteria

| Criterion | Evidence |
| --- | --- |
| `shipments.parquet` generated | 283 rows (spec expects 275–290) |
| `shipment_items.parquet` generated | 469 rows (spec expects 450–550) |
| `shipment_status_history.parquet` generated | 1,379 rows (spec expects 1200–1400) |
| Shipments originate only from CAPTURED payments | Asserted in both directions, plus a validation rule |
| One shipment per payment | Declared unique, plus a rule that no captured payment is missed |
| Shipment items originate only from order lines | Every item joins an order line of its own shipment's order |
| Tracking numbers deterministic | Derived by bijection from `shipment_id`; seed-independent and unique at 40x scale |
| Carrier determined from shipping method | Membership checked against the configured table |
| Status history chronological | Time and lifecycle position both advance with the sequence |
| Validation passes | Zero issues on generated data |
| CLI passes | `eds generate commerce` exits 0 and writes eleven datasets |
| Unit tests pass | 1,424 passed (was 1,260; F008 adds 164) |
| Ruff passes | All checks passed |
| MyPy passes | No issues in 167 source files |
| Deterministic output | Frame equality at generator, orchestrator, and CLI levels |

Completion reach at the default scale: `CREATED`/`PACKED`/`SHIPPED` 283 (100%),
`IN_TRANSIT` 276 (97.5%), `DELIVERED` 254 (89.8%), against the documented
90 / 7 / 3 split of final statuses — observed 89.8 / 7.8 / 2.5.

Carrier split: STANDARD 200 shipments across UPS 69, FedEx 69, DHL 62;
EXPRESS 57 across DHL Express 34, FedEx Priority 23; NEXT_DAY 15 and
STORE_PICKUP 11, each to their single carrier.

## Design decisions

### The shipment has its own lifecycle, not the order's

F006's `OrderStatus` docstring notes that `PACKED`, `SHIPPED` and `DELIVERED`
"belong to later features". F008 is that feature — but it does **not** extend
`OrderStatus`. F006 is frozen under ADR-006, and ADR-011 asks for one lifecycle
per business entity. A new `ShipmentStatus` enum carries the fulfilment stages,
and `orders.current_status` is left exactly as F006 wrote it.

### The status history owns the entire timeline

ADR-012 makes the history the source of truth. That is easy for a single
`current_status` field, but `shipments` also carries `shipped_at` and
`delivered_at`, and the intermediate `PACKED` and `IN_TRANSIT` moments are not
columns at all.

Rather than compute the waits twice — once for the document, once for the
history — the status generator draws all four waits and produces every stage,
and `apply_status_and_timeline` reads `current_status`, `shipped_at` and
`delivered_at` back out of it. There is exactly one place where a shipment's
timeline is decided, and a validation rule proves the columns match the rows
they were derived from.

### Tracking numbers are a bijection, not a hash

"Unique" and "deterministic" together rule out sampling: a random ten-digit
body across many shipments is only *probably* unique, and a hash has the same
birthday problem. The generator instead computes
`(shipment_id * 2654435761 + 7246913) mod 10^10`. The multiplier is odd and not
a multiple of five, so it is coprime to the modulus, which makes the map a
bijection — two shipments cannot collide, by construction rather than by luck.
It is also seed-independent, fully vectorised, and looks like a real tracking
number. A test generates 40x the fixture and asserts uniqueness at that scale.

### Carrier selection is a scaled draw, not a lookup

The carrier depends on the shipping method, but most methods offer several. The
generator joins a per-method carrier count onto each shipment, scales its
uniform draw across that count, and joins the resulting index back to the
carrier table. A method with one option always yields that option; a method
with three spreads across all three. No Python loop, and no per-method branch.

### The estimate is promised at creation

`estimated_delivery_at` is measured from `created_at` rather than `shipped_at`.
The promise is made to the customer when the shipment is created, before anyone
knows when the parcel will actually leave the depot. It also keeps the estimate
computable in the shipment generator, where the method's day window is already
joined. The independent rule that `delivered_at` follows `shipped_at` is
unaffected, and both are validated.

### The configuration layer stays domain-free

`shipments.yaml` is keyed by shipping method, which tempts a
`from eds.domain.commerce.enums import ShippingMethod` in `eds/config.py`. That
module imports nothing from `eds.domain` today, and adding it would change the
layering for one validation. Instead the config checks the tables structurally
— non-empty, non-inverted, non-negative — and the generator raises a named
`KeyError` if a method present in the data has no carrier. That catches the
failure that actually matters; a typo'd key fails at generation with a clear
message rather than at load time.

## Assumptions

1. **A shipment is created for every captured payment, including six whose
   order has no lines.** Every item in those carts was removed before checkout
   — an F006 known limitation — but the order still carries shipping and tax,
   so it was paid for. "Exactly one shipment per captured payment" is stated
   unconditionally, so the shipment exists and carries no items.
2. **`created_at` is the payment's `captured_at` plus a configured lead**
   (one second by default). Every captured payment has a capture time.
3. **The shipment number sequence is per-day, not global**, matching F006 and
   F007. Numbers stay globally unique because the date is part of the string.
4. **The tracking number body is ten digits.** The specification writes
   `TRK-XXXXXXXXXX` without saying what `X` is; digits satisfy the format and
   let the uniqueness guarantee be arithmetic.
5. **Every shipment reaches `SHIPPED`.** The three completion shares sum to
   100% and none of them stops at `CREATED` or `PACKED`, so `shipped_at` is
   never null.
6. **`STORE_PICKUP` is modelled as an ordinary shipment** with a same-day
   estimate and a "Store Pickup" carrier. The specification lists it in the
   carrier table, so it produces a shipment like any other method.
7. **The whole order ships at once.** Split shipments and backorders are out of
   scope, so `order_line_id` is declared unique across `shipment_items`.

## Test coverage

1,424 tests total; F008 contributes 164.

| Area | Tests | Notable failure paths |
| --- | --- | --- |
| Shipments, items, history, config | 96 | Missing upstream datasets; no captured payments; completion shares that do not sum to one; inverted waits and delivery windows; an empty carrier list; a method with no carrier configured; delivered and shipped rates driven to 1.0 |
| Shipment validation | 53 | Every documented check proved by injecting the defect, including all seven foreign keys and a malformed number that must be reported rather than raised on |
| CLI | 15 | A config override that must not reset settings; byte-identical upstream files; determinism across invocations |

The completion-distribution test runs against the payment fixture replicated
forty times. The session fixture carries a few dozen captured payments, which
cannot distinguish a 3 per cent outcome from a 7 per cent one; replication gives
the shares a sample they can be read from, so the tolerances stay tight (±2–3
points) rather than wide enough to pass on noise. The same replicated fixture
proves both that a multi-carrier method really spreads across all its options
and that tracking numbers stay unique at scale.

A CLI test reads every earlier Parquet file before and after the run and
asserts the bytes are unchanged, and another switches every carrier to Royal
Mail, both prefixes, and the delivered rate to 100% via a config file to prove
the settings survive a `--seed` override — the regression ADR-003 exists for.

## Defects found and fixed

1. **A conditional skip was replaced with a real test.** The store-pickup
   same-day case skipped when the fixture happened to contain no such shipment;
   it now switches every checkout to `STORE_PICKUP` and asserts the estimate
   equals the creation moment.

## Known limitations

1. **Six shipments carry no items.** Their order has no lines because every
   cart item was removed before checkout. Arguably such an order should not
   ship at all, but that judgement belongs to F004 and F005, both frozen.
2. **Progress is a coin flip.** A shipment that stopped at `IN_TRANSIT` did so
   by a draw, not because of its carrier, its distance, or how recently it was
   created. A shipment created on the last simulated day is as likely to be
   delivered as one from a year earlier.
3. **The estimate is never compared against reality.** Nothing marks a
   shipment as late, even though `delivered_at` frequently falls after
   `estimated_delivery_at` — the transit waits and the promised window are
   drawn independently.
4. **`STORE_PICKUP` is shipped, packed and delivered like a parcel.** A real
   pickup has no carrier leg; modelling it properly needs a store entity.
5. **The lifecycle stops at `DELIVERED`.** `RETURNED`, `LOST` and `DAMAGED` are
   deliberately absent from the enum rather than declared and unused. A later
   feature will need to add them to `ShipmentStatus` and `SHIPMENT_LIFECYCLE`.
6. **An order's status is not advanced by its shipment.** F006 is frozen, so a
   `PROCESSING` order can have a `DELIVERED` shipment against it.
7. **One warehouse, one parcel, one carrier.** Multiple warehouses, split
   shipments and backorders are all out of scope, so `shipment_items` is
   exactly the order's lines.
8. **The daily shipment-number boundary is global**, using the shipment's local
   timestamp, which carries no timezone — the same limitation F006 and F007
   record.

## Suggested improvements

- Let the shipment's age drive how far it progressed, so a parcel created
  yesterday is still in transit while one from last year has arrived.
- Flag late deliveries by drawing the actual transit time around the promised
  window rather than independently of it.
- Reconcile order status against shipment progress once the frozen F006
  lifecycle is open for revision, so a delivered shipment can complete its
  order.
- Model `STORE_PICKUP` against a store entity, with a ready-for-collection
  status instead of a carrier leg.
- Add `RETURNED`, `LOST` and `DAMAGED` to `SHIPMENT_LIFECYCLE` as part of the
  returns feature, with the return dataset driving the transitions.
- Assign a warehouse per shipment once inventory allocation exists, which is
  also the prerequisite for split shipments and backorders.
