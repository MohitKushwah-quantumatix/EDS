# F010 - Review

| Field | Value |
| --- | --- |
| Outcome | Complete; volume below the stated range for the reason set out below |
| Environment | Windows 10, Python 3.13.0 |
| Verified | `pytest`, `ruff check .`, `ruff format --check .`, `mypy eds`, end-to-end CLI run |

## Acceptance criteria

| Criterion | Evidence |
| --- | --- |
| `reviews.parquet` generated | 58 rows (spec expects 70–90 — see below) |
| Reviews originate only from delivered shipment items | Asserted in both directions, plus a validation rule |
| Returned shipment items never generate reviews | Asserted against `return_items`, plus a validation rule |
| One review per shipment item | Declared unique, plus a rule that no item is reviewed twice |
| Review numbers deterministic | Format, uniqueness, embedded date, and per-day sequence all asserted |
| Rating configuration driven | Weights honoured; a single-rating config yields only that rating |
| Titles configuration driven | Substituted config reaches the data; a rule rejects wording the rating never offered |
| Review text configuration driven | Same, plus a one-sentence shape assertion |
| Verified purchase always TRUE | Column asserted true with no nulls, plus a validation rule |
| Timeline valid | `created_at` after `delivered_at`, within the configured window |
| Validation passes | Zero issues on generated data |
| CLI passes | `eds generate commerce` exits 0 and writes fifteen datasets |
| Unit tests pass | 1,700 passed (was 1,582; F010 adds 118) |
| Ruff passes | All checks passed |
| MyPy passes | No issues in 181 source files |
| Deterministic output | Frame equality at generator, orchestrator, and CLI levels |

Rating split at the default scale: 5★ 23 (39.7%), 4★ 17 (29.3%), 3★ 6 (10.3%),
2★ 7 (12.1%), 1★ 5 (8.6%), against the documented 40 / 30 / 15 / 10 / 5 — a
sample of 58 cannot resolve those shares more finely. Measured against the
shipment fixture replicated forty times the split matches within 4 points.

## The volume shortfall

**58 reviews against an expected 70–90.** This is arithmetic, not a defect, and
it is worth setting out precisely.

The eligible population is fixed by F008 and F009, both frozen:

| Quantity | Count |
| --- | --- |
| Shipment items | 469 |
| On `DELIVERED` shipments | 423 |
| Less items that were returned | −42 |
| **Eligible** | **381** |

At the specification's suggested 18 per cent, the expected count is
381 × 0.18 = **68.6**, which is *below* the stated 70–90 range before any
sampling noise. The range implies about 444 eligible items at 18 per cent, or a
rate of about 21 per cent against the 381 that actually exist.

Measured over forty seeds the generator produces a mean of 67.0 and an
empirical rate of 0.1759 against the configured 0.18 — the rate is correct.
The spread is 52–88, and 14 of 40 seeds land inside 70–90. Seed 42 gives 58.

**The rate was left at the documented 18 per cent.** It is the figure the
specification names, it is configuration driven, and raising it to 21 per cent
to centre one seed in the range would be fitting the parameter to the target.
Anyone who wants the stated volume changes one line:

```yaml
# configs/reviews.yaml
review_rate: 0.21
```

This is the same class of finding as the F006 order-line shortfall and the F009
return-count spread: the expected range was computed against an assumed
upstream that differs from what the pipeline actually produces.

## Design decisions

### Eligibility is a conjunction, and both halves are tested separately

Delivered *and* not returned. An item that arrived and was sent back is
excluded even though the customer saw it — whatever they thought of it, the
transaction is not the one this feature describes. Two independent tests assert
each half, so neither can silently stop being applied, and the validator checks
both against the data rather than trusting the generator.

### The wording is selected, never generated

ADR-009 prefers derived data over random data, and the specification is
explicit that titles and bodies come from configuration. Both are looked up by
the *drawn rating*, so a three-star review can only carry three-star wording.
The validator enforces this as a join against the configured tables: a phrase
that the rating never offered is an issue, not just an oddity. That check is
skipped when the tables are not supplied, because nothing else knows what was
on offer — the same pattern F009 used for refund types.

The configuration validator refuses a `titles` or `texts` table that does not
cover every rating `rating_weights` can produce, so the failure surfaces at load
time rather than as a silently dropped row in an inner join.

### The rating draw is fully vectorised

`Expr.cut` maps the uniform draw onto cumulative weight boundaries in one
operation, so the number of ratings stays configuration driven without a Python
loop over rows. F009 used a per-row helper for refund types; this is the better
shape and the one to prefer if that code is ever revisited.

### One dataset, no history

Every earlier commerce feature produced a parent, a collection, and a status
history. A review has none of those: it is written once, and edits and
moderation are out of scope, so there is no lifecycle to record. `REVIEW_DATASETS`
is a one-element tuple and `reviews` carries no `current_status`. A test asserts
both, so a future feature that adds review moderation has to do it deliberately.

### Everything but the product comes from the shipment

ADR-008 gives the review one parent: the shipment item. `product_id` comes from
the item; `shipment_id`, `order_id` and `customer_id` are copied down from the
shipment the item arrived in. The validator checks each against its source, so a
review can never claim a product its item did not carry.

## Assumptions

1. **`verified_purchase` is a constant true**, not a drawn value. Every review
   originates from a delivered shipment, so there is no unverified case. It is
   kept as a column because consumers expect it, and a validation rule asserts
   it rather than leaving it as a silent invariant.
2. **`created_at` may equal `delivered_at`** when `min_review_days` is zero. The
   specification says the review is "after" delivery; same-instant is treated as
   satisfying that, and the default minimum of one day means it does not arise.
3. **The review number sequence is per-day, not global**, matching F006 to F009.
   Numbers stay globally unique because the date is part of the string.
4. **A shipment item is reviewed at most once**, declared as a unique column.
5. **`customers.parquet` is an F002 dataset** despite being listed under F001 in
   the specification. The file exists either way.
6. **The test fixtures raise the review rate well above the shipped 18 per
   cent.** At fixture scale 18 per cent would yield too few reviews to assert a
   rating distribution against; the shipped default is asserted separately
   against `reviews.yaml`.

## Test coverage

1,700 tests total; F010 contributes 118.

| Area | Tests | Notable failure paths |
| --- | --- | --- |
| Reviews and configuration | 68 | Missing upstream datasets; nothing delivered; everything returned; rating weights that do not sum to one; a rating outside 1–5; wording that does not cover every rating; an empty phrase list |
| Review validation | 34 | Every documented check proved by injecting the defect, including all five foreign keys, a returned item that was reviewed, and a malformed number that must be reported rather than raised on |
| CLI | 16 | A config override that must not reset settings; byte-identical upstream files; determinism across invocations |

The tests that matter most here are the two eligibility halves and the wording
lookup: one substitutes a configuration containing only `Custom Title` and
asserts every review uses it, another sets a single rating weight and asserts
only that rating appears, and a third asserts a five-star title attached to a
three-star review is rejected.

The rating-distribution and review-rate tests run against the shipment fixture
replicated forty times, because a few dozen reviews cannot distinguish a 5 per
cent outcome from a 10 per cent one.

## Defects found and fixed

1. **Seven count assertions in earlier features broke** once the commerce
   command emitted a fifteenth dataset: five pipeline file counts (38 → 39) and
   two report-total assertions. The two report totals were replaced with
   dataset-name assertions, which is what those tests are actually about — the
   pipeline test owns the total. That removes the recurring breakage this
   pattern has caused in F007, F009 and F010.

## Known limitations

1. **The volume is below the stated range** for the arithmetic reason set out
   above. One configuration line closes it.
2. **The rating is unrelated to everything else.** A customer who waited three
   weeks for a late delivery is as likely to leave five stars as one whose
   parcel arrived next day, and the product being reviewed has no bearing on its
   own rating. Nothing in the data would let an analyst find a genuine
   product-quality signal, because there is none to find.
3. **The wording carries no information beyond the rating.** Two five-star
   reviews of entirely different products can be word-for-word identical, and
   with two or three phrases per rating that happens constantly at scale.
4. **Only one review per item, and none from anyone else.** Unverified reviews,
   reviews from customers who bought elsewhere, and repeat reviews after an
   exchange all fall outside the model.
5. **A product with many sales gets proportionally many reviews**, because the
   draw is per item with no per-product ceiling or fatigue. Real review counts
   are far more skewed than sales counts.
6. **No review is ever edited, voted on, replied to, or moderated** — all
   explicitly out of scope, and all absent from the schema rather than present
   and unused.
7. **The daily review-number boundary is global**, using the review's local
   timestamp, which carries no timezone — the same limitation F006 to F009
   record.

## Suggested improvements

- Let the delivery experience drive the rating: a shipment that missed its
  `estimated_delivery_at` should skew low, which would give the dataset a real
  signal to find and would connect F008 to F010.
- Give each product a latent quality drawn once, so ratings cluster per product
  rather than being independent draws — the single change that would most
  improve the dataset's analytical value.
- Widen the phrase pools, or compose the body from a rating-appropriate opening
  and a product-category clause, so identical text is rarer at scale.
- Add a per-product review ceiling or a declining hazard, so review counts skew
  more sharply than sales counts as they do in reality.
- Allow unverified reviews once there is a source for them, making
  `verified_purchase` a genuine discriminator rather than a constant.

---

## Enterprise Data Simulator v1.0

F010 is the last feature. The complete pipeline is four commands producing
**39 datasets**:

| Command | Datasets | Features |
| --- | --- | --- |
| `master-data` | 14 | F001 |
| `customers` | 4 | F002 |
| `journey` | 6 | F003.1, F003.2, F003.3 |
| `commerce` | 15 | F004 – F010 |

At the default 1,000-customer scale that is 8,035 commerce rows on top of
144,855 master, customer and journey rows, every one of them referentially
consistent, chronologically ordered, and reproducible from a seed.
