# F009 - Review

| Field | Value |
| --- | --- |
| Outcome | Complete; all three volume targets met |
| Environment | Windows 10, Python 3.13.0 |
| Verified | `pytest`, `ruff check .`, `ruff format --check .`, `mypy eds`, end-to-end CLI run |

## Acceptance criteria

| Criterion | Evidence |
| --- | --- |
| `returns.parquet` generated | 35 rows (spec expects 28–35) |
| `return_items.parquet` generated | 42 rows (spec expects 35–50) |
| `return_status_history.parquet` generated | 168 rows (spec expects 140–170) |
| Returns originate only from DELIVERED shipments | Asserted in both directions, plus a validation rule |
| One return per shipment | Declared unique, plus a rule that no shipment is returned twice |
| Return items originate only from shipment items | Every item joins a shipment item of its own return's shipment |
| Return numbers deterministic | Format, uniqueness, embedded date, and per-day sequence all asserted |
| Return reasons loaded from master data | Declared as a foreign key onto `return_reasons.reason_code`; a substituted master table changes the data |
| Refund types loaded from configuration | Membership checked against the configured table; a config override reaches the data |
| Status history chronological | Time and lifecycle position both advance with the sequence |
| Validation passes | Zero issues on generated data |
| CLI passes | `eds generate commerce` exits 0 and writes fourteen datasets |
| Unit tests pass | 1,582 passed (was 1,424; F009 adds 158) |
| Ruff passes | All checks passed |
| MyPy passes | No issues in 175 source files |
| Deterministic output | Frame equality at generator, orchestrator, and CLI levels |

Completion reach at the default scale: `COMPLETED` 31 (88.6%), `RECEIVED` 2,
`IN_TRANSIT` 1, `APPROVED` 1, against the documented 85 / 8 / 5 / 2 — a sample
of 35 cannot resolve those shares more finely.

Reasons used: LATE_DELIVERY 11, DAMAGED 8, DEFECTIVE 6, WRONG_ITEM 6,
CHANGED_MIND 4 — all five master rows exercised. Settlement: FULL_REFUND 22,
STORE_CREDIT 9, REPLACEMENT 4.

## The ADR-006 exception

**`return_reasons.parquet` did not exist**, yet the specification named it as
an F001 dependency and made "return reasons loaded from master data" an
acceptance criterion. F001 shipped thirteen master datasets and this was not
one of them.

Implementation stopped and the technical lead chose between three options that
each broke a standing instruction. **The decision was to add `return_reasons`
to F001**, which is an explicit, authorised exception to ADR-006 and to
"completed features are immutable".

What changed in F001, and nothing else:

- `RETURN_REASONS` added to `COMMERCIAL_DATASETS` — five curated rows, in the
  same fixed-catalogue style as payment methods and coupon types.
- `generate_return_reasons()` added beside the other commercial generators.
- The F001 orchestrator emits it; the registry is otherwise untouched.
- `eds generate master-data` now writes fourteen files rather than thirteen.

No existing F001 dataset, column, or row changed. The four test assertions that
counted thirteen datasets were updated, as were the pipeline file counts
(23 → 24 after the journey command, 34 → 38 after commerce).

This is recorded prominently because a future reader will otherwise read the
change as a violation rather than an authorised exception.

## Design decisions

### The reason is a foreign key, the refund type is not

`return_reason` is declared as a foreign key onto `return_reasons.reason_code`,
so the referential validator rejects any value the master table does not carry
— the vocabulary cannot drift out of the data. `refund_type` gets no such edge
because it has no master table; it is checked against the configured mapping
passed into the validator, and the check is skipped when that mapping is not
supplied. The asymmetry is deliberate and mirrors where each vocabulary lives.

### Only active reasons are offered, and an empty table is an error

The generator filters on `is_active` and raises `ValueError` if nothing
remains, rather than falling back to a literal. That is the point of reading
from master data: if the table says there are no reasons, there is no return to
attribute, and inventing one would defeat the requirement.

### A return brings back some or all of what arrived

Returning every item of every returned shipment would put the item count at 50
— the exact ceiling of the expected 35–50 — and would misrepresent the common
case of one damaged item out of three. Each return instead brings back between
one and all of its shipment's items: a uniform draw per item ranks them within
the return, a second draw picks how many, and the top-ranked survive. That
lands at 42 items across 35 returns (1.2 each), mid-range.

Quantities within an item are never split. Partial-quantity returns would need
a `quantity <= shipped` model and a refund calculation, both out of scope.

### The status history owns the whole timeline

ADR-012 makes the history the source of truth. `returns` carries `approved_at`,
`received_at` and `completed_at`, and the `IN_TRANSIT` moment is not a column
at all. Rather than compute the waits twice, the status generator draws all
four and produces every stage, and `apply_status_and_timeline` reads the three
timestamps and `current_status` back out. A validation rule proves the columns
match the rows they came from — in both directions, so a null on one side and a
value on the other is caught.

### Returns get their own lifecycle

`ReturnStatus` is separate from `ShipmentStatus` even though both carry an
`IN_TRANSIT`: there the parcel travels to the customer, here it travels back.
ADR-011 asks for one lifecycle per business entity, and F008 made the same call
about `OrderStatus`.

### Expression-based generation, no row loops

All three datasets are built as expression pipelines. The draws are taken as
whole vectors up front. The eligibility draw is taken over every eligible
shipment, but the reason, settlement and delay draws are taken only for the
shipments that were actually selected — keeping the random stream short and the
intent legible.

## Assumptions

1. **A delivered shipment with no items is not eligible.** The objective says
   returns originate from delivered shipment *items*. Four such shipments exist
   at the default scale, inherited from the F006 empty-order limitation.
2. **`created_at` equals `requested_at`.** The document exists when the
   customer asks; there is no earlier moment to record. A validation rule
   asserts it.
3. **`requested_at` may equal `delivered_at`** when `min_request_days` is zero.
   The specification says the request is "after" delivery; same-instant is
   treated as satisfying that, and the default minimum of one day means it does
   not arise in practice.
4. **The return number sequence is per-day, not global**, matching F006 to
   F008. Numbers stay globally unique because the date is part of the string.
5. **A shipment item comes back at most once**, declared as a unique column.
   Exchanges are out of scope.
6. **Every return reaches `APPROVED`.** The four completion shares sum to 100%
   and none stops at `REQUESTED`, so `approved_at` is never null. Rejections
   are explicitly out of scope.
7. **The test fixtures raise the return rate well above the shipped 12%.** At
   fixture scale 12% would yield a handful of returns, too few to assert a
   lifecycle against; the shipped default is asserted separately against
   `returns.yaml`.

## Test coverage

1,582 tests total; F009 contributes 158.

| Area | Tests | Notable failure paths |
| --- | --- | --- |
| Returns, items, history, config, master data | 92 | Missing upstream datasets; a master table with no active reason; no delivered shipments; shares that do not sum to one; inverted waits; rates driven to 0 and 1 |
| Return validation | 50 | Every documented check proved by injecting the defect, including all seven foreign keys, the reason foreign key, and a malformed number that must be reported rather than raised on |
| CLI | 16 | A config override that must not reset settings; byte-identical upstream files; determinism across invocations |

The reason-lookup tests are the ones that matter most for this feature: one
substitutes a master table containing only `MISSING_PARTS` and asserts every
return uses it, another deactivates all but one reason, and a third asserts the
generator raises rather than inventing a reason when the table is empty. A
fourth asserts no field of `ReturnConfig` mentions a reason, so the vocabulary
cannot quietly migrate into configuration.

The completion-distribution and return-rate tests run against the shipment
fixture replicated forty times, because a few dozen returns cannot distinguish
a 2 per cent outcome from a 5 per cent one.

## Defects found and fixed

1. **Four count assertions in earlier features broke** once F001 emitted a
   fourteenth dataset: the F001 registry and output-set tests, the journey
   pipeline file count, and two commerce report counts. All were factually
   wrong rather than wrongly written, and were updated.
2. **Two CLI report tests asserted a total dataset count** that every new
   feature invalidates. Those assertions were dropped in favour of naming the
   datasets the test is actually about, so F010 will not break them again.
3. A `Series.min()` comparison that mypy could not narrow, replaced with a
   frame-level filter.

## Known limitations

1. **The expected range is narrower than the sampling noise.** Across forty
   seeds the return count spans 23–40 with a mean of 30.05 against a
   theoretical 30.0 — the rate is exactly right, but a 12% rate on 250 eligible
   shipments has a standard deviation of about 5, so only 26 of 40 seeds land
   inside the stated 28–35. Seed 42 gives 35. The rate was left at the
   documented 12% rather than tuned to centre one seed in the range.
2. **Progress is a coin flip.** A return that stopped at `IN_TRANSIT` did so by
   a draw, not because of its reason, its carrier, or how recently it was
   requested. A return requested on the last simulated day is as likely to be
   completed as one from a year earlier.
3. **The reason does not influence anything else.** A `CHANGED_MIND` return is
   as likely to be approved and completed as a `DEFECTIVE` one, and
   `requires_inspection` is recorded in master data but never acted on.
4. **No money moves.** Refund payments, chargebacks and store-credit issuance
   are out of scope, so a `FULL_REFUND` return has no financial record against
   it and the payment it relates to is untouched.
5. **A `REPLACEMENT` return ships nothing back out.** Replacement shipments are
   out of scope, so the settlement type is recorded but has no downstream
   effect.
6. **Nothing is restocked.** Inventory is untouched by a completed return.
7. **The lifecycle has no unhappy path.** `REJECTED` and `CANCELLED` are
   deliberately absent from the enum, so every return that is requested is
   approved. A later feature will need to add them to `RETURN_LIFECYCLE`.
8. **The daily return-number boundary is global**, using the request's local
   timestamp, which carries no timezone — the same limitation F006 to F008
   record.

## Suggested improvements

- Let the reason drive the outcome: a `CHANGED_MIND` return could be rejected
  or restocked immediately, a `DEFECTIVE` one could require inspection before
  approval, using the `requires_inspection` flag the master table already
  carries.
- Let the return's age drive how far it progressed, so a request from last week
  is still in transit while one from last year has completed.
- Add `REJECTED` and `CANCELLED` to `RETURN_LIFECYCLE` so not every request
  succeeds, with `is_customer_fault` influencing the rejection rate.
- Issue the refund as a financial record once a refund-payment feature exists,
  closing the loop back to F007.
- Restock received items into F001 inventory once inventory movement is
  modelled.
- Allow partial-quantity returns, which needs a `quantity <= shipped` model and
  a refund calculation to go with it.
