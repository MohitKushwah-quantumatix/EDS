# ADR-006 - Feature Immutability

**Status:** Accepted

**Applies from:** F006

---

## Decision

Completed features are frozen. Once a feature has been accepted:

- Its schemas are immutable.
- Its dataset names are immutable.
- Downstream features consume them as-is.
- Only correctness bugs may justify a change.

Future features must never redesign previous features.

---

## Consequences

A new feature that needs a different shape from an existing dataset must
either derive what it needs at read time, or declare its own dataset. It may
not widen, rename, or re-type a frozen one.

Adding a dataset to a *capability* is still allowed - what is frozen is the
existing declaration, not the namespace. The established pattern is a new
registry tuple beside the old one rather than an edit to it.

---

## Current state

Already followed from F003.2 onward, before this ADR was written:

| Feature | Added | Left untouched |
| --- | --- | --- |
| F003.2 | `BROWSING_DATASETS` | `JOURNEY_DATASETS` |
| F003.3 | `ENGAGEMENT_DATASETS` | `JOURNEY_DATASETS`, `BROWSING_DATASETS` |
| F005 | `CHECKOUT_DATASETS` | `COMMERCE_DATASETS` |

Each of those features carries a test asserting the earlier registries still
declare exactly their own datasets, so a later edit fails the suite rather
than passing silently.

---

## Exception already on record

The F003.1 review records that `pages_viewed` on `sessions` drifts from what
F003.2 and F003.3 generate. Under this ADR that column is now frozen, so the
reconciliation suggested in those reviews would require either a correctness
argument or a new dataset. It cannot be fixed by widening `sessions`.
