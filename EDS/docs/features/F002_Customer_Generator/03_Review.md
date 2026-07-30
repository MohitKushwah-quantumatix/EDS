# F002 - Review

| Field | Value |
| --- | --- |
| Outcome | Complete |
| Environment | Windows 10, Python 3.13.0 |
| Verified | `pytest`, `ruff check .`, `ruff format --check .`, `mypy eds`, end-to-end CLI run |

## Verification

| Deliverable | Result |
| --- | --- |
| All datasets generated | 4 of 4 - customers, addresses, preferences, loyalty |
| Validation passes | Zero issues on generated data |
| CLI works | `eds generate customers` exits 0 |
| Unit tests pass | 387 passed (was 262; F002 adds 125) |
| Ruff passes | All checks passed |
| MyPy passes | No issues in 95 source files |
| Parquet exported | 4 files written alongside the F001 output |
| Deterministic | Frame equality at generator, orchestrator, and CLI levels |

End-to-end run with the shipped configuration: 1,000 customers, 1,495
addresses, 1,000 preferences, 1,000 loyalty records.

## Architecture

F002 follows the F001 shape exactly: declarative `Dataset` schemas, Polars
frames, named RNG streams, a bundle object, a validation entry point, and a
CLI command.

```
F001 parquet  ->  reader  ->  CustomerGeography
                                    |
                                    v
                       customers -> addresses
                                 -> preferences
                                 -> loyalty
                                    |
                                    v
                        validation  ->  parquet
```

### The home city, and why it matters

Each customer is assigned one **home city** drawn from the F001 cities
dataset. That single assignment drives:

- the address's `city_id`, `state_id`, `country_id`, and `postal_code`,
- the customer's `preferred_language` and `preferred_currency`,
- the preference record's `timezone`.

The assignment is a pure function of `(config, geography, seed)`, so each
generator recomputes it rather than receiving it through a parameter chain.
This keeps the four generators independently callable while guaranteeing they
agree. A test asserts the customer and preference records carry identical
language and currency, which would fail if the assignment ever drifted.

### Reuse rather than duplication

`validate_referential_integrity` gained one optional parameter - the dataset
declarations to check, defaulting to the F001 master datasets. F002 passes its
own declarations. Duplicate emails, phones, and customer numbers are therefore
caught by the existing unique-column machinery, and orphan geography
references by the existing foreign key machinery. No customer-specific
referential code was written. A regression test asserts F001 validation still
returns zero issues after the change.

## Assumptions made

1. **F002 reads F001's exported Parquet files** rather than regenerating
   master data. `eds generate customers` loads `countries`, `states`, and
   `cities` from the output directory (or `--master-data`), and fails with
   exit code 2 and the message "Run `eds generate master-data` first" when
   they are absent. This required a new `eds/exporters/parquet/reader.py`,
   placed beside the writer so the file naming convention stays in one place.
2. **`reference_date` is configurable and defaults to 2026-01-01.** Anchoring
   the five-year registration window to `date.today()` would mean a seeded run
   produced different data tomorrow, breaking the determinism deliverable.
3. **`lifecycle_stage` is derived, not sampled.** The specification lists the
   column but gives no distribution. It is computed from account status and
   tenure - closed maps to churned, suspended to at risk, inactive to dormant,
   and an active account under 90 days old to onboarding - so the stage can
   never contradict the status printed beside it.
4. **Loyalty `status` is derived from account status** for the same reason: a
   closed account never carries an active membership.
5. **`points_balance` is derived from tenure**, multiplied by a per-tier
   earning rate with variation. The specification asks that older customers
   generally hold more points; sampling points independently of tier would not
   satisfy it. Tier itself follows the documented 60/25/10/5 split.
6. **All of a customer's addresses sit in their home city**, differing by
   street line, type, and jittered coordinates. Placing a second address in a
   random unrelated city would undercut the internal-consistency principle.
7. **The primary address is always typed `HOME`**; secondary addresses are
   work, shipping, billing, or other.
8. **Uniqueness is guaranteed, not hoped for.** Email and phone are generated
   naturally and fall back to a customer-id-derived value on collision, so the
   uniqueness rules hold at any customer count rather than only at small ones.
9. **Customer enums live in `eds/domain/customer/enums.py`**, not in the F001
   `eds/domain/enums.py`, so F002 adds no risk to master data.
10. **Language mapping is explicit** for the six countries F001 supports,
    defaulting to `en-US`. Preferences and customer records read from the same
    mapping.
11. **Preference and loyalty identifiers reuse the customer id.** Both are
    strictly one-to-one, so a separate counter would carry no information.

## Test coverage

387 tests total; F002 contributes 125.

| Area | Tests | Notable failure paths |
| --- | --- | --- |
| Customer generator | 26 | Empty cities, states, or countries each raise |
| Addresses, preferences, loyalty | 24 | Empty customers frame raises |
| Orchestrator and configuration | 24 | Each missing F001 dataset; empty geography; inverted address bounds |
| Customer validation | 26 | Every documented rule proved by injecting the defect |
| Parquet reader | 6 | Missing file names the next command to run |
| CLI | 13 | Missing master data, bad config dir, sub-minimum count |

Distribution tests assert the documented splits within tolerance on samples of
3,000-6,000 customers: segment 35/40/20/5, status 94/3/2/1, email verification
92%, mobile 90%, loyalty tier 60/25/10/5, and a risk-score mean of 25 with
under 5% above 75.

The validation tests are the load-bearing ones. Each corrupts a valid bundle
and asserts the specific rule fires, covering every rule the specification
lists: duplicate emails, phones, customer numbers, and ids; missing addresses;
orphan city, state, country, and customer references; two primary addresses
and zero primary addresses; and customers missing a preference or loyalty
record.

## Defects found and fixed during implementation

1. `generate_cities` in F001 was called with a `locale` argument that lived on
   the wrong config object - already fixed in F001, and F002's signatures were
   written to take locale explicitly for the same reason.
2. A test used `pl.date(...)`, which builds an expression rather than a value,
   and raised inside `pl.lit`. Replaced with `datetime.date`.
3. Two tests compared Polars aggregate results whose static type is a wide
   union. Rewritten to compare plain Python values.

## Out of scope, as instructed

No login history, browsing, search, wishlist, cart, orders, payments,
sessions, events, recommendations, or fraud engine. F003 has not been started.

## Improvements not implemented

- Segment-aware behaviour: VIP customers currently share the same address
  count, verification rates, and risk distribution as new customers.
- Correlation between `customer_segment` and `tier`; a VIP customer can hold a
  bronze membership.
- Household modelling - several customers sharing an address.
- Locale-aware names and phone formats. All names come from the `en_US` Faker
  locale and phone numbers use a `+1` pattern even for non-US countries.
- Email domains are `example.*` reserved names; a realistic mix of consumer
  providers would read better in demos.
- Streaming Parquet output, which F001's review already records as the shared
  ceiling on dataset size.
