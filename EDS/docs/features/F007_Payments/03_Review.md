# F007 - Review

| Field | Value |
| --- | --- |
| Outcome | Complete; both volume targets met |
| Environment | Windows 10, Python 3.13.0 |
| Verified | `pytest`, `ruff check .`, `ruff format --check .`, `mypy eds`, end-to-end CLI run |

## Acceptance criteria

| Criterion | Evidence |
| --- | --- |
| `payments.parquet` generated | 309 rows (spec expects 300–320) |
| `payment_status_history.parquet` generated | 596 rows (spec expects 580–620) |
| Payments originate only from orders | Asserted in both directions, plus a validation rule |
| One payment per payable order | Declared unique, plus a rule that no payable order is missed |
| Amount copied from the order | Compared for **exact** equality, not a tolerance |
| Method copied from the checkout | Joined via the order's `checkout_id` and compared |
| Provider derived from the method | Mapping is total over `PaymentMethod`; a rule fires on any disagreement |
| Currency read from configuration | Single distinct value; a config override reaches the data |
| Payment references deterministic | Format, uniqueness, embedded date, and per-day sequence all asserted |
| Status history chronological | Timestamps advance with the sequence; transitions checked against the lifecycle |
| `payment_status` matches the history | Derived by `apply_payment_status`; a rule proves the two agree |
| Validation passes | Zero issues on generated data |
| CLI passes | `eds generate commerce` exits 0 and writes eight datasets |
| Unit tests pass | 1,260 passed (was 1,135; F007 adds 125) |
| Ruff passes | All checks passed |
| MyPy passes | No issues in 159 source files |
| Deterministic output | Frame equality at generator, orchestrator, and CLI levels |

Outcome split at the default scale: CAPTURED 283 (91.6%), FAILED 22 (7.1%),
VOIDED 4 (1.3%), against the configured 92 / 5 / 3. History rows: 287 payments
with two rows, 22 with one.

Payment total reconciles exactly with the order total it was copied from:
$194,283.12 on both sides, across 309 payments and the 311 orders that carry
them (two orders are billed at zero and are not charged).

## Design decisions

### The payment method comes from the checkout, because nothing else has it

The specification says the method must be copied from the checkout, but lists
only `customers`, `payment_methods` and `orders` as dependencies. `orders`
carries no `payment_method` column, so the rule cannot be satisfied from the
declared inputs alone.

Rather than re-draw a method - which would break the stated rule and ADR-007 -
the generator reads one column from `checkout`, reached through the order's own
`checkout_id`. `checkout` is already in the commerce command's input set, so
this adds no new read to the pipeline.

### `payment_methods.parquet` is declared but not used

The F001 reference table was checked before being dismissed. Its codes are
carrier-level (`VISA`, `MC`, `AMEX`, `DISC`, `DEBIT`, `PAYPAL`, ...); the F005
checkout vocabulary the provider mapping is defined over is `UPI`,
`CREDIT_CARD`, `DEBIT_CARD`, `NET_BANKING`, `WALLET`, `COD`. The two sets do
not intersect, so a join would match nothing and a foreign key would fail on
every row. It is therefore not read, and no key is declared against it - the
same decision F005 reached about `shipping_methods`.

### The payment document is built, then finalised

ADR-012 makes `payment_status_history` the source of truth and
`payment_status` a derived convenience. The pipeline is therefore: draw each
payment's outcome and build the document, generate the history from it, then
call `apply_payment_status` to set the status from each payment's latest
history row. The value is the same either way; deriving it in that direction is
what a validation rule can then prove. This mirrors F006's `current_status`.

### A failed payment was never authorised

The lifecycle the specification gives is `AUTHORIZED → CAPTURED`,
`AUTHORIZED → VOIDED`, `FAILED`. `FAILED` is not a successor of `AUTHORIZED`,
so a failed attempt never reached authorisation: it gets a single history row,
stamped with the attempt, and `authorized_at` stays null. Two validation rules
tie the timestamps to the status - `authorized_at` is populated exactly when
the payment is not `FAILED`, and `captured_at` exactly when it is `CAPTURED`.

This is also what makes the history volume land where the specification expects
it: 309 payments at 0.92 x 2 + 0.03 x 2 + 0.05 x 1 rows is 602 against an
expected 580–620.

### Money is copied and compared exactly

ADR-007 makes the order the single source of financial truth for a payment, so
`payment_amount` is carried across untouched. The validator compares it for
**exact** equality rather than within a cent: a value that had been recomputed
- even correctly - would almost never land on the identical float, so exact
comparison is what actually detects a recalculation.

### Expression-based generation, no row loops

Both datasets are built as expression pipelines. The payment generator's draws
- the outcome roll and the capture wait - are taken as whole vectors up front
and attached as columns, so assembly stays vectorised while remaining
reproducible from the seed. The status generator concatenates one frame per
status and needs only a single extra draw, for the void wait; every other
timestamp is read off the payment.

### Payment references restart each day

`PAY-YYYYMMDD-000001` embeds a date, so the sequence is scoped to that date -
`pl.int_range(...).over("payment_date")`. Payments are sorted by their order's
creation time before numbering, so the same input always yields the same
references, with or without a seed.

## Assumptions

1. **An order billed at zero or less is not charged.** There is nothing to
   authorise. Two orders at the default scale are in this position, because
   every item in their cart was removed before checkout - an F006 known
   limitation, and F006 is frozen. A validation rule asserts the exclusion in
   both directions.
2. **`created_at` is the order's `created_at` plus a configured lead** (one
   second by default), and `authorized_at` equals `created_at` for a payment
   that was authorised. The record and the authorisation are the same moment;
   the wait that varies is the one before capture or voiding.
3. **The reference's date is the payment's own date**, not the order's. The
   two can differ when the authorisation lead crosses midnight. A validation
   rule ties the embedded date to `created_at`.
4. **The reference sequence is per-day, not global.** The format embeds a
   date, which only makes sense if the sequence restarts with it. References
   stay globally unique because the date is part of the string.
5. **F007 is single-currency.** The specification says the currency is read
   from configuration and never inferred, so every payment in a run carries the
   configured value. A validation rule fires if more than one code appears.
6. **`AUTHORIZED` never appears as a final `payment_status`.** Every payment
   settles within the run: F007 leaves nothing in flight, because a pending
   authorisation would need a later feature to resolve it.
7. **`payments.py` was added as the orchestrator**, matching every earlier
   feature. The specified module structure lists only the two generators.
8. **The payment document is never rewritten.** `apply_payment_status` returns
   a new frame during generation, before anything is written; the exported
   document is produced once.

## Test coverage

1,260 tests total; F007 contributes 125.

| Area | Tests | Notable failure paths |
| --- | --- | --- |
| Payments, status history, config | 73 | Missing upstream datasets; no orders at all; an order billed at zero; outcome shares that do not sum to one; inverted wait ranges; capture, void and failure rates driven to 1.0 |
| Payment validation | 39 | Every documented check proved by injecting the defect, including both foreign keys and a malformed reference that must be reported rather than raised on |
| CLI | 13 | A config override that must not reset settings; byte-identical upstream files; determinism across invocations |

The outcome-distribution test runs against the order fixture replicated forty
times. The session fixture carries about thirty payments, which cannot
distinguish a 3 per cent outcome from a 5 per cent one; replication gives the
shares a sample they can be read from, so the tolerances are tight (±2–3
points) rather than wide enough to pass on noise.

A CLI test reads every earlier Parquet file before and after the run and
asserts the bytes are unchanged, and another drives the capture rate to 100%
and the currency to GBP via a config file to prove both the settings and the
prefix survive a `--seed` override - the regression ADR-003 exists for.

## Defects found and fixed

1. **The validation tests named the wrong rule.** Three asserted
   `invalid_foreign_key`; the referential validator emits `orphan_reference`
   and `missing_reference_dataset`. Caught by the tests themselves.
2. **The outcome-distribution test failed on the session fixture** - 83.9%
   captured against 92% ± 5 on 31 payments. Fixed by measuring against a
   replicated order set rather than by widening the tolerance.
3. **A conditional skip was replaced with a real test.** The zero-total order
   case skipped when the fixture happened to contain no such order; it now
   zeroes one explicitly and asserts the payment is not created.

## Known limitations

1. **Every payment settles in one pass**, so a payment that failed did so by a
   draw rather than because anything about it - its amount, its method, its
   customer - made it more likely. A cash-on-delivery payment authorises and
   captures exactly like a card.
2. **The void wait is drawn for every payment**, including those that capture
   or fail, so the stream stays aligned with the dataset. The unused draws are
   discarded; this costs nothing but is worth knowing when reasoning about the
   seed.
3. **`COD` is modelled as an ordinary authorise-and-capture flow.** Cash on
   delivery is really captured at delivery, which needs a shipment - F008.
4. **No payment is ever retried.** A failed payment is terminal, so an order
   whose payment failed simply has no money against it. Retries are explicitly
   out of scope.
5. **The lifecycle stops at capture.** `REFUNDED` and `CHARGEBACK` are
   deliberately absent from the enum rather than declared and unused, so no
   dataset can claim a status nothing generates. A later feature will need to
   add them to `PaymentStatus` and `PAYMENT_TRANSITIONS`.
6. **An order with a failed or voided payment still shows its F006 lifecycle
   status.** F006 is frozen, so `orders.current_status` is not revisited; a
   `PROCESSING` order whose payment failed is possible in the data.
7. **The reference's daily boundary is global**, using the payment's local
   timestamp, which carries no timezone - the same limitation F006 records for
   order numbers.

## Suggested improvements

- Let the method, amount, or customer influence the outcome, so a failure has
  a reason rather than a coin flip - card payments failing more often than UPI,
  large amounts more often than small.
- Model `COD` as authorised at order and captured at delivery once F008
  provides the shipment to hang the capture on.
- Add payment retries as a follow-up feature, with a retry sequence on the
  payment and the history recording each attempt.
- Reconcile order status against payment outcome once the frozen F006 lifecycle
  is open for revision, so a failed payment can hold its order back.
- Derive the daily reference sequence from the customer's timezone rather than
  a single global boundary, now that F002 records one per customer.
