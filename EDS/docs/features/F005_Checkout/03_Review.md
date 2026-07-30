# F005 - Review

| Field | Value |
| --- | --- |
| Outcome | Complete |
| Environment | Windows 10, Python 3.13.0 |
| Verified | `pytest`, `ruff check .`, `ruff format --check .`, `mypy eds`, end-to-end CLI run |

## Acceptance criteria

| Criterion | Evidence |
| --- | --- |
| `checkout.parquet` generated | 376 rows (spec expects 330–420) |
| Every checkout references an existing cart | Declared foreign key, declared unique so a cart checks out once |
| Every checkout references an existing customer | Declared foreign key plus a match against the cart's customer |
| Every checkout references an existing session | Declared foreign key plus a match against the cart's session |
| Valid customer addresses | Two declared foreign keys, plus a rule that both belong to the checking-out customer |
| Only CHECKED_OUT carts generate a checkout | Asserted in both directions: no ineligible cart appears, and no eligible cart is missing |
| `subtotal` is correct | Recomputed from `cart_items` and compared to the cent |
| `total_amount` is correct | Reconciled against the sum of its parts |
| Timeline validation passes | Completion after start, start after the cart settled, completion flag agrees with status |
| Referential integrity passes | Zero issues on generated data |
| CLI works | `eds generate commerce` exits 0 and writes three datasets |
| Unit tests pass | 1,000 passed (was 910; F005 adds 90) |
| Ruff passes | All checks passed |
| MyPy passes | No issues in 144 source files |
| Deterministic output | Frame equality at generator and CLI levels |

Measured at the default scale: 376 checkouts from 376 checked-out carts,
status 82.7/8.5/8.8 against the documented 82/8/10, shipping 70/20.5/4.5/5,
and payment 36/24/15/10/10/4.

## Design decisions

### F004's registry was left untouched

Adding the checkout to `COMMERCE_DATASETS` would have changed a previous
feature's declared output and broken its tests for no good reason. The
checkout is declared in its own `CHECKOUT_DATASETS` tuple instead - the same
pattern F003.2 and F003.3 used when extending the journey command - and a test
asserts F004's registry still holds exactly its own two datasets.

### Cart status and checkout status answer different questions

A `CHECKED_OUT` cart can produce a `FAILED` or `ABANDONED` checkout. F004
records that the customer intended to pay; F005 records how that attempt
ended. Reading the two as the same thing would make 18% of checkouts
impossible.

### Money is computed, not sampled

The subtotal is summed from the cart's own items and the total is the sum of
its parts, both rounded to the cent. The validator recomputes the subtotal
from `cart_items` independently, so the figures reconcile against upstream
data rather than merely looking plausible. Every component is rounded before
the total is formed, so the reconciliation is exact to within a cent.

### Shipping and payment use F005's own vocabularies

The specification lists exact strings - `NEXT_DAY`, `UPI`, `COD` - which do
not appear in the F001 `shipping_methods` and `payment_methods` reference
tables, and it declares no foreign key to either. They are therefore modelled
as checkout-level enums, and the enum docstrings say so explicitly to stop a
later feature from assuming a join that does not exist.

### A single-address customer bills to that address

Address selection takes the primary address for shipping, then bills to the
same one unless the customer has another and the configured reuse rate says
otherwise. A customer with one address on file always has identical shipping
and billing, which is what the specification allows and what a test asserts
against the 505 single-address customers in the default run.

## Assumptions

1. ~~**The subtotal includes items the customer later removed.**~~
   **Superseded.** F005 originally summed every cart item, following the
   specification's formula literally. This was subsequently ruled a
   correctness bug and fixed under ADR-007: the subtotal now sums only items
   with a null `removed_at`, and `tax_amount` and `total_amount` follow from
   it. See the architecture-corrections entry below.
2. **Tax is a flat rate per checkout**, drawn from the configured band and
   applied to the subtotal. The F001 `tax_codes` table exists but the
   specification neither lists it as a dependency nor gives the checkout a tax
   code column.
3. **The checkout may run past the session's recorded end.** A session's
   `end_time` is its last page view, and F004 can leave a cart last touched at
   exactly that moment, so requiring the checkout inside the session would be
   unsatisfiable. It is required to start after the cart settled instead.
4. **`created_at` equals `started_at`** - the row is written when the attempt
   begins, which is the only moment every status shares.
5. **A customer with no address on file produces no checkout.** This cannot
   happen with F002 data, which guarantees at least one address, but the
   generator skips rather than inventing an address.
6. **`discount_amount` is always zero**, as the specification instructs until
   promotions exist.

## Test coverage

1,000 tests total; F005 contributes 90.

| Area | Tests | Notable failure paths |
| --- | --- | --- |
| Generator and configuration | 48 | Each of five missing upstream datasets; empty addresses; no eligible carts; inverted ranges |
| Checkout validation | 27 | Every documented check proved by injecting the defect, including all five foreign keys |
| CLI | 15 | Missing addresses; a config override that must not reset settings |

Distribution tests for status, shipping method, and payment method run against
a deliberately enlarged sample rather than the small shared fixture, so a
±5-point assertion measures the generator rather than sampling noise.

A CLI test reads every earlier Parquet file before and after the run and
asserts the bytes are unchanged, and another fixes the tax band and address
reuse rate through a config file to prove the settings survive a `--seed`
override.

## Defects found and fixed

1. **A distribution test failed on the shared fixture.** The small test
   configuration yields 38 checkouts, where a ±7-point assertion on a 15%
   category is meaningless - `DEBIT_CARD` landed at 5.3%. The generator was
   correct at scale (15% across 376 rows). Fixed by giving the three
   distribution tests a replicated cart set and tightening the tolerances,
   which now measure the intended behaviour instead of the fixture size.
2. A test annotated an enum parameter as bare `type`, which mypy rejects as
   not iterable - the same slip as in two earlier features, fixed the same way
   with `type[StrEnum]`.

## Architecture corrections applied after acceptance

**Subtotal excludes removed cart items.** Only items still in the cart at
checkout contribute to `subtotal`, and therefore to `tax_amount` and
`total_amount`. The generator and the validator both apply
`removed_at IS NULL`, and four tests cover it: the corrected recomputation,
that a cart which lost an item is charged less than everything ever added,
that tax and total follow the corrected figure, and that a fully emptied cart
is charged shipping alone. A validation test asserts that a checkout priced
against every item no longer reconciles.

This is the only post-acceptance change to F005 and was made under the
correctness-bug exception in ADR-006.

---

## Known limitations

1. **`checkout_status` is independent of everything else.** Basket value,
   payment method, and customer risk score all exist upstream, but none
   influences whether an attempt fails. A COD checkout fails as often as a
   card one.
2. **Tax ignores geography.** The rate is drawn from a flat band rather than
   derived from the shipping address's country, even though F001 generates
   country-specific `tax_codes` and F002 gives every address a country.
3. **Shipping cost ignores the basket.** It is drawn from the method's band
   regardless of weight, value, or distance, all of which exist upstream.
4. **A `FAILED` checkout carries no reason.** The specification says a reason
   is not required, so the column does not exist - a retry or a failure-reason
   breakdown is not possible from this data alone.
5. **`ABANDONED` checkouts have no duration.** With `completed_at` null there
   is no record of how long the customer hesitated before leaving.

## Suggested improvements

- Derive the tax rate from the shipping address's country using the F001
  `tax_codes` table, which already carries per-country rates.
- Let basket value and payment method influence the failure rate - card
  declines and COD refusals behave differently.
- Scale shipping cost with the basket's weight, which F001 records per product
  and F004 can aggregate per cart.
- Record an abandonment moment for abandoned checkouts, so the drop-off point
  can be analysed without inferring it.
- Reconcile the F005 shipping and payment vocabularies with the F001 reference
  tables, so a single set of codes serves both master data and transactions.
