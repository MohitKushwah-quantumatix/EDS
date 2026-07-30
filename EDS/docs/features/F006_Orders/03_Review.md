# F006 - Review

| Field | Value |
| --- | --- |
| Outcome | Complete, with one volume shortfall caused by frozen upstream data |
| Environment | Windows 10, Python 3.13.0 |
| Verified | `pytest`, `ruff check .`, `ruff format --check .`, `mypy eds`, end-to-end CLI run |

## Acceptance criteria

| Criterion | Evidence |
| --- | --- |
| `orders.parquet` generated | 311 rows (spec expects 300–350) |
| `order_lines.parquet` generated | 513 rows (spec expects 600–900 - see below) |
| `order_status_history.parquet` generated | 879 rows (spec expects 900–1100 - see below) |
| Orders originate only from SUCCESS checkouts | Asserted in both directions, plus a validation rule |
| One order per checkout | Declared unique, plus a rule that no successful checkout is missed |
| Financial values copied from checkout | Compared for **exact** equality, not a tolerance |
| Order lines reconcile with totals | Sum of lines equals the copied subtotal |
| Removed cart items excluded | Lines matched against active items; a rule fires if a removed one leaks |
| Order numbers deterministic | Format, uniqueness, embedded date, and per-day sequence all asserted |
| Status history chronological | Time and lifecycle position both advance with the sequence |
| Validation passes | Zero issues on generated data |
| CLI passes | `eds generate commerce` exits 0 and writes six datasets |
| Unit tests pass | 1,135 passed (was 1,005; F006 adds 130) |
| Ruff passes | All checks passed |
| MyPy passes | No issues in 152 source files |
| Deterministic output | Frame equality at generator, orchestrator, and CLI levels |

Lifecycle reach at the default scale: CREATED 311 (100%), CONFIRMED 291
(93.6%), PROCESSING 277 (89.1%), against the documented 100 / 95 / 90.

## Design decisions

### The order document is built, then finalised

ADR-012 makes `order_status_history` the source of truth and
`current_status` a derived convenience. That inverts the obvious generation
order, because an order's status cannot be known before its history exists.

The pipeline is therefore: build the orders with `current_status` set to
`CREATED`, generate the history, then call `apply_current_status` to replace
the placeholder with the status of each order's latest history row. Every
intermediate frame is schema-valid, and a validation rule proves the two agree
in the finished data.

### Money is copied and compared exactly

ADR-007 makes the checkout the single source of financial truth, so the five
financial columns are carried across untouched. The validator compares them
for **exact** equality rather than within a cent: a value that had been
recomputed - even correctly - would almost never land on the identical float,
so exact comparison is what actually detects a recalculation.

### Lines and totals reconcile because they share one rule

The order's subtotal is copied from the checkout, and F005 computes that
subtotal over cart items with no `removed_at`. F006 draws its lines from the
same active items. Neither side is adjusted to match the other; they agree
because they apply the same rule to the same data.

Two validation rules keep it honest: the lines must sum to the subtotal, and
every line must match an active cart item of the order's own cart. A third
rule fires if a removed item ever appears as a line.

### Expression-based generation, no row loops

The specification asks for Polars and no row-by-row loops. All three datasets
are built as expression pipelines: orders from a filter and a set of
`with_columns`, lines from a single join, and history by concatenating one
frame per lifecycle stage.

The status generator needs randomness, so its draws are taken as whole vectors
up front and attached as columns. That keeps the assembly vectorised while
staying reproducible from the seed.

### Order numbers restart each day

`ORD-YYYYMMDD-000001` embeds a date, so the sequence is scoped to that date -
`pl.int_range(...).over("order_date")`. Orders are sorted by completion time
before numbering, so the same input always yields the same numbers. Because
`order_date` is derived from `created_at` rather than sampled, the date inside
the number can never disagree with the order's own date; a validation rule
asserts it anyway.

## Assumptions

1. **`order_date` is the date of `created_at`.** The two are derived from one
   value rather than assigned separately, which is what makes the order
   number's embedded date reliable.
2. **`created_at` is the checkout's `completed_at` plus a configured lead**
   (one second by default). Every successful checkout has a completion time,
   so this is always defined.
3. **The order number sequence is per-day, not global.** The format embeds a
   date, which only makes sense if the sequence restarts with it. Numbers stay
   globally unique because the date is part of the string.
4. **`processing_rate` is expressed over all orders**, not over confirmed
   ones. It is rescaled internally against the confirmed share so the
   documented 90% is the share of *all* orders that reach `PROCESSING`. The
   configuration rejects a processing rate above the confirmed rate.
5. **An order with no lines is valid.** Ten orders at the default scale have
   had every cart item removed. Their subtotal is zero, so they reconcile.
   Suppressing them would mean a successful checkout with no order, which
   breaks a stated rule.
6. **`orders.py` was added as the orchestrator**, matching every earlier
   feature. The specified module structure lists only the three generators.
7. **The order document is never rewritten.** `apply_current_status` returns a
   new frame during generation, before anything is written; the exported
   document is produced once.

## Test coverage

1,135 tests total; F006 contributes 130.

| Area | Tests | Notable failure paths |
| --- | --- | --- |
| Orders, lines, history, config | 70 | Missing upstream datasets; no successful checkouts; a processing rate above the confirmed rate; zero and full lifecycle rates |
| Order validation | 45 | Every documented check proved by injecting the defect, including all nine foreign keys |
| CLI | 15 | Missing products; a config override that must not reset settings |

The financial-copy test is parametrised over all five money columns and shifts
each by a single cent, so a recalculation that happened to be close would
still fail.

A CLI test reads every earlier Parquet file before and after the run and
asserts the bytes are unchanged, and another drives the lifecycle to 100% via
a config file to prove both the settings and the prefix survive a `--seed`
override.

## Defects found and fixed

1. **The order number validator crashed instead of reporting.** Given a
   malformed number, the per-day sequence check tried to parse its last six
   characters as an integer and raised rather than adding an issue. The check
   now runs only on rows that match the format; the malformed ones are
   already reported by the rule above it. Caught by its own test.
2. A set comprehension written as a generator expression, flagged by Ruff.

## Known limitations

1. **Order line volume falls below the expected range: 513 against 600–900.**
   This is not a defect in F006 - it follows arithmetically from frozen
   upstream data. F004 generates 1.86 cart items per cart, about 1.65 after
   removals, and F005 converts 311 carts. Even at the top of the expected
   order range, 350 orders would yield about 578 lines. The expected range
   implies roughly 2.0–2.6 lines per order, which F004 does not produce.
   Reaching it needs a change to F004's cart size distribution, which ADR-006
   freezes.
2. **Status history is 879 against an expected 900–1100**, for the same
   reason: 311 orders x 2.85 stages is 886 at best. The range implies about
   316–386 orders.
3. **Ten orders carry no lines.** Every item in their cart was removed before
   checkout, so their subtotal is zero. Arguably those carts should not have
   become successful checkouts at all, but that judgement belongs to F004 and
   F005, both frozen.
4. **The lifecycle stops at `PROCESSING`.** `PACKED`, `SHIPPED` and
   `DELIVERED` are deliberately absent from the enum rather than declared and
   unused, so no dataset can claim a stage nothing generates. A later feature
   extending the lifecycle will need to add them to `ORDER_LIFECYCLE`.
5. **Every order's history is generated in one pass**, so an order that
   stopped at `CONFIRMED` did so by a draw rather than because anything about
   it - its value, its payment method, its customer - made it more likely.
6. **`order_date` uses the checkout's local timestamp**, which carries no
   timezone. A single global date boundary is assumed for the order number's
   daily sequence.

## Suggested improvements

- Let order value or payment method influence how far the lifecycle advances,
  so a stalled order has a reason rather than a coin flip.
- Reconsider whether a cart whose items were all removed should reach a
  successful checkout, once F004 and F005 are open for revision.
- Add `PACKED`, `SHIPPED` and `DELIVERED` to `ORDER_LIFECYCLE` as part of the
  fulfilment feature, with the shipment dataset driving the transitions rather
  than a rate.
- Record an actor on each status transition once a user, operator or warehouse
  entity exists - the `changed_by` column ADR-010 removed for lack of a source.
- Derive the daily order number sequence from the customer's timezone rather
  than a single global boundary, now that F002 records one per customer.
