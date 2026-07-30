# ADR-002 - Generate Causality, Not Coincidence

**Status:** Accepted

**Applies from:** F003.1 (documented retrospectively)

---

## Decision

A generated fact must be caused by the facts that precede it. Two rows that
happen to agree are not the same as one row that follows from another.

Where a downstream value can be **computed** from an upstream one, compute it.
Where it can only be **constrained**, constrain it at the point of generation
rather than hoping a validator will notice.

---

## Why

Coincidence is fragile. A generator that samples a plausible-looking value and
a validator that checks the same range will agree with each other and be
wrong together. Causality survives a change in either.

The difference shows up whenever a feature is extended: a coincidental value
has to be re-tuned every time an upstream distribution moves, while a caused
value follows it automatically.

---

## What this looks like in practice

**Derive rather than assert.** `shopping_carts.item_count` is counted from the
cart items that were actually created, not written first and checked later.
Its `created_at` and `updated_at` bracket the real add and remove times.

**Constrain at generation, validate independently.** A search timestamp is
built as `view.timestamp + 1..view.duration`, which satisfies three separate
rules at once - inside the session, after the first category view, during that
category page. The validator then checks all three against the data rather
than trusting the construction.

**Make the impossible unrepresentable.** `purchase_probability` is computed as
`cart_probability x conversion ratio` rather than sampled, so a persona can
never be more likely to buy than to reach a cart.

**Let one decision drive its consequences.** A customer's home city fixes
their address geography, their language, their currency, and their session
timezone. One draw, four coherent facts.

---

## Consequences

Generation order follows causality, which sometimes means a two-pass shape:
plan the parents, generate the children, then finalise the parents from what
the children became. F004 does exactly this, and the alternative - writing an
aggregate first and hoping the children match - is what this ADR rules out.

A validator must recompute independently rather than re-reading the
generator's own logic. Where the two share code, they share a *declaration*
(the dataset schema) rather than a calculation.

---

## Counter-example on record

F003.1's `pages_viewed` was sampled per session before F003.2 and F003.3
existed. Both later features generate page-level activity without consulting
it, so the three can disagree. That column is coincidental rather than caused,
and both reviews record it as a limitation. It is frozen under ADR-006.
