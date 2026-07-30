# ADR-013: History Is the State

**Status:** Accepted (Retail Temporal Evolution)

**Applies from:** the Retail temporal layer onward.

**Related:** ADR-005 (deterministic generation), ADR-006 (feature
immutability), ADR-010 (state history over mutable state), ADR-012 (business
document immutability), PADR-010 (the platform owns simulated time), PADR-014
(the runner is a third party).

**Generalised by:** PADR-016 (`docs/platform/`), which keeps only what is not
about retail - that a domain derives its state from persisted business data and
keeps no execution state - and makes it binding on every domain. This record is
the worked example; PADR-016 is the rule.

## Context

Retail generated an enterprise as of a fixed `reference_date` in
`customers.yaml`. Given a seed, it produced the same thirty-nine datasets every
time it ran - which was correct for a snapshot and useless for a simulation.
P006.1 wired Retail into the platform scheduler and recorded the consequence:
**a multi-day run regenerated identical data and overwrote itself.**

The platform supplies a simulated date to every stage. This decision is about
what Retail does with it.

## Decision

Three rules, and everything else follows from them.

### 1. The execution date is the reference date

The business date supplied for a unit of work is the date that work is
generated relative to. `customers.reference_date` remains, as the default for a
caller with no date to offer - which is what `eds generate` is - so the CLI
behaves exactly as it did.

What Retail receives is one value object,
`eds.domains.retail.temporal.context.BusinessContext`: a date and a seed. There
is no clock in it, no tick, no calendar, no run and no project. Retail cannot
ask what time it is and cannot advance it.

### 2. A stage founds itself the first time it runs

There is no tick counter and no "first run" flag. A stage whose own datasets
are empty has no history to continue, so it builds one; a stage that has
history continues it.

That single rule absorbs every awkward case. A run that stopped half-way
through the founding day and was picked up later founds the stages that never
ran and evolves the ones that did. A run started a year after the last one
continues from what is on disk. An enterprise carried between machines carries
its whole position with it, because **the data is the state** - not a
checkpoint, not a tick index, not a manifest.

### 3. A day is seeded by its date, not by its position

Every generator called for a business day is seeded from
`stream_seed(enterprise_seed, f"{stream}@{date}")`. A tick *index* would make a
day's business depend on how the run reached it; a date does not.

The consequence is the strongest property this layer has, and it is tested by
comparing bytes: **nine days run at once and nine days run as four then three
then two produce the same enterprise.** Determinism therefore survives being
interrupted, divided, resumed or continued months later.

### How a day is generated

By the founding generators, given day-shaped inputs.

The alternative - a second implementation of "how a retail business behaves",
one for founding and one for growth - would have to be kept in step with the
first for ever, and would drift the week nobody was looking. So the customer
configuration is told today is the reference date, the personas are told how
many sessions fit in a day, and the commerce chain is shown only the sessions
that happened today. What comes back is a day of business, produced by the same
rules as the founding five years, by the same code, with the same tests behind
it.

Four things are then true before it joins history, and all four are the
business of `eds.domains.retail.temporal.identity`:

| Problem | Rule |
| --- | --- |
| Generators number from one | Every primary key shifts past the largest already issued; foreign keys pointing at *today's* rows shift with it, older ones do not. Driven by the `Dataset` declarations, so a new dataset is handled the day it is declared. |
| `CUST-00000042` renders customer 42 | Codes that render an identifier are rebuilt from the shifted one. |
| `ORD-20260304-000001` counts within a day | A later day can ship, refund or review against a date an earlier day opened, so the sequence continues that date's count. **History keeps its numbers.** |
| An email address must be unique for ever | Checked against everything ever issued and rewritten with the generator's own fallback rule. Same rule, wider memory. |

### What each day changes

New customers register, dated today. Everybody who registers gets a persona,
and those who registered before today may come back - weighted by the persona
the founding day gave them - and open a session, browse categories, search,
view products and add to a wishlist. Today's browsing becomes today's carts,
checkouts, orders, payments, shipments, returns and reviews. Stock falls by
what has been sold and is replenished in whole reorder lots. Loyalty balances
catch up with lifetime spending.

`configs/evolution.yaml` holds the four rates that describe change rather than
shape, and is the only optional configuration file: a directory written before
Retail could evolve has no opinion about how a day changes an enterprise, and
should still load.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| **Rewrite the generators to be incremental** | Twenty generators, sixty modules and roughly seventeen hundred tests, to arrive at code that can no longer produce a founding snapshot. The byte-identical guarantee would be gone on day one. |
| **A second set of "growth" generators** | Two implementations of one business, kept in step by hope. |
| **Keep a tick index in project state** | Makes a day's business depend on the shape of the run that reached it, which is exactly what breaks resume and division. The date is already in the request. |
| **Track the last processed day in the data** | A new column in a dataset whose bytes must not change, to record something the timestamps already say. |
| **Let the runner overwrite `reference_date`** | Puts a business rule in the integration layer. The domain decides what a date means to it. |
| **Decrement stock rather than recompute it** | Requires knowing which orders have already been applied, which requires state, which requires the run's shape. Recomputing from reproducible opening stock and cumulative demand needs neither. |
| **Trim rows dated after the business day** | A day's commerce settles its whole chain, so a parcel shipped tomorrow is generated today (see below). Trimming it would mean a later day revisiting old orders, which means reading the whole order history to find the ones not yet settled. |

## Consequences

**Good.** A year of trading is a year of business: three hundred and sixty-five
consecutive days, each adding to the last, with no rewritten row, no repeated
identifier, no repeated business key and no broken temporal rule.

**Good.** The founding day is unchanged, so `eds generate` is unchanged and the
platform path still produces output byte-identical to it.

**Good.** Generation moved out of the runner and into the domain. P006.1 had to
put it in `eds/runners/retail/stages.py` because Retail had no notion of being
run; it has one now, so the runner classifies failures and nothing else.

**Cost.** Validation runs over the accumulated history on every stage of every
day, which makes a long run slower than a linear one. Several rules are about a
*date* rather than a row - order, payment, shipment, return and review numbers
must run `1..n` without gaps for each day - and a later day can add to a date
an earlier day opened, so those rules cannot be checked against the day alone.

**Cost.** A day is not idempotent. Re-running a business date against a history
that already contains it appends that day's business a second time, because
identifiers continue from what exists. Nothing in the platform asks for that -
the scheduler records each stage once and a resume skips what completed - and a
test pins the behaviour so that a reader does not have to guess.

**Limitation.** A day's commerce settles its entire chain on the day of the
order, so a parcel that arrives next week and the review written a month later
are generated today. Relationally everything is in order and the temporal rules
prove it; but the datasets contain rows dated after the business date, and a
consumer reading "the enterprise as at today" would see the future. Splitting
settlement across the days it falls on is the fix, and it needs the commerce
stage split first (PADR-014, finding 2).

## Domain questions this raised

Running for a year asks questions a snapshot never had to answer. What follows
is a record of them, not an implementation of them.

### Should products discontinue, and should prices evolve?

**1. Existing behaviour.** `products` is classified `STATIC`. The catalogue the
founding day creates is the catalogue for ever: no product is introduced,
withdrawn or repriced.

**2. Proposed evolution.** Make it `SLOWLY_CHANGING`. A product gains an
`updated_at` movement when its price changes, and a withdrawn product keeps its
row and its identifier with a status that stops it being ordered. New products
append.

**3. Advantages.** Price history is the single most requested thing in a retail
dataset - margin analysis, elasticity, promotion effectiveness all need it, and
none of them can be answered from one price per product. A catalogue that never
changes over a simulated decade is the least believable thing in the data.

**4. Disadvantages.** An order line records `unit_price`, so a repriced product
makes the line and the catalogue disagree unless the line is read as *the price
on the day*, which is correct but is a reading a consumer has to be told about.
Withdrawing a product means the commerce chain must learn to avoid it, which
touches four generators.

**5. Compatibility impact.** `products.parquet` gains no column, so the founding
day is unaffected and the byte-identical guarantee holds. Every consumer that
joins to `products` for a price silently changes meaning from "the price" to
"the current price". That is a documentation change, not a code change, which
is what makes it dangerous.

**6. Recommendation.** **Do it, and do prices before discontinuation.** Price
movement is where the value is, needs no new dataset and no new column, and is a
`SLOWLY_CHANGING` merge that already exists. Discontinuation should wait for the
commerce stage to be split, because that is where the "may this be ordered"
question has to be asked.

### Should inactive customers return, and should active ones leave?

**1. Existing behaviour.** Who comes back on a given day is a weighted draw
against the persona the founding day assigned. A customer's `lifecycle_stage`
is derived when they register and never revisited, so somebody who has not
visited for three simulated years is still `ACTIVE`.

**2. Proposed evolution.** Derive the stage from behaviour: a customer with no
session for so many days becomes `DORMANT`, then `CHURNED`; a dormant customer
who returns becomes `ACTIVE` again. `customers` becomes `SLOWLY_CHANGING` for
that column and `updated_at`.

**3. Advantages.** Churn and reactivation are the two things a retail dataset is
most often *for*, and neither can be derived today - not even by a consumer,
because the stage says the opposite of what the sessions say.

**4. Disadvantages.** `customers` stops being append-only, which weakens the
strongest statement this ADR makes about it. The rule needs a window in days,
which is another rate to configure and to defend.

**5. Compatibility impact.** No schema change. `lifecycle_stage` becomes a
function of history rather than of registration, so the existing test that it
never contradicts `status` must be re-derived. Rows change, so a consumer
snapshotting `customers` sees movement where there was none.

**6. Recommendation.** **Defer, but not for long.** It is the most valuable of
these questions and the one that costs the most: it is the first thing that
would make a customer row mutable, and doing it well means deciding what a
lifecycle stage *is* - a derived view or a recorded fact. That is worth its own
decision, and ADR-010 already says which way this codebase leans.

### Should suppliers, warehouses and stores change?

**1. Existing behaviour.** All `STATIC`. The supply chain the founding day
creates is permanent.

**2. Proposed evolution.** Let suppliers be taken on and dropped, and
warehouses opened and closed, at low rates.

**3. Advantages.** Realistic for a simulated decade.

**4. Disadvantages.** Closing a warehouse invalidates the inventory rows that
point at it, and dropping a supplier orphans the products it supplied. Both
need a policy, and the policy is more interesting than the feature.

**5. Compatibility impact.** Inventory would need rows removed rather than
replaced, which is a fifth temporality rather than a use of the four.

**6. Recommendation.** **No.** This is realism nobody is asking for, at the cost
of the referential integrity everything else rests on. Revisit only if a
consumer needs supply-chain change specifically.

### Should promotions expire?

**1. Existing behaviour.** `coupon_types` is `STATIC` reference data and no
dataset records a promotion being *run*.

**2. Proposed evolution.** A promotions dataset with a validity window,
referenced by checkout discounts.

**3. Advantages.** It would explain the discounts, which are currently an
unexplained number on a checkout.

**4. Disadvantages.** A new dataset and a new generator, and the discount logic
in F005 has to be rewritten to draw from it.

**5. Compatibility impact.** Additive - a fortieth dataset - but `checkout`
gains a foreign key, which changes its schema and its bytes.

**6. Recommendation.** **Not now.** It is a new feature wearing a temporal
question's clothes, and it should be requested as one.

## What this decision does not permit

Retail may not read a clock, ask what day it is, or advance a date. A test
asserts that no module in the temporal package mentions `datetime.now`,
`date.today`, `time.time` or `utcnow`, and another asserts that nothing in
`eds/domains/retail/` imports the platform's run, scheduler, runtime, time or
project packages, at any depth.

A day may not alter a row an earlier day wrote, except where the dataset's
declared temporality says it may - and only two of the thirty-nine do
(ADR-014). Where a day *does* rewrite, the movement must be monotonic: a
loyalty balance is the greater of what was recorded and what spending has
earned, which is the one formula that makes accumulation independent of how the
run was divided.
