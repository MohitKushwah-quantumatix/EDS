# ADR-009 - Derived Data Preferred Over Random Data (Commerce Chain)

**Status:** Accepted

**Applies from:** F006

**Extends:** [ADR-001](ADR-001-derived-data-over-random-data.md)

---

## Relationship to ADR-001

ADR-001 states this principle for the simulator as a whole and was applied
from F001 onward. This ADR adds no new rule: it names the parents for the
commerce entities specifically, so a feature implementing orders or payments
does not have to infer them.

The two share a title because they are the same decision at two scopes. If
they are ever consolidated, ADR-001 is the one to keep.

---

## Decision

Transactional entities are derived from their parent, not sampled.

| Entity | Derived from |
| --- | --- |
| Order | Checkout |
| Payment | Order |
| Shipment | Order |
| Review | Delivered order line |

Customers and products are never randomly sampled for a transactional
dataset.

---

## Consequences

Randomness decides *attributes* - a status, a duration, a method - not
*existence* or *identity*. If a generator needs a product, it takes the one
its parent already points at.

The practical test: removing all randomness from a generator should still
leave every foreign key valid and every row attributable to a real parent.

---

## Current state

Already followed throughout. The pattern each feature used:

| Feature | What is derived | What is sampled |
| --- | --- | --- |
| F003.2 | Search category inherits its category view's | Search phrase, result count |
| F003.3 | Product drawn from the browsed category's subtree; wishlist product copied from the view | Popularity weighting, dwell time |
| F004 | Cart item product copied from its product view or wishlist entry | Quantity, cart status |
| F005 | Subtotal summed from the cart; customer and session copied from the cart | Shipping method, payment method, tax rate |

F001 is the deliberate exception: master data has no transactional parent, so
products, brands, and suppliers are generated rather than derived. Even there,
countries and their subdivisions are real reference data rather than sampled.

---

## Interaction with ADR-007

Where the two overlap, ADR-007 is the stronger constraint: a monetary value is
not merely derived from the parent, it is *copied* from the checkout. Deriving
it by recalculation - even correctly - violates ADR-007.
