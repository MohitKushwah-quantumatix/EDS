# ADR-001 - Derived Data Preferred Over Random Data

**Status:** Accepted

**Applies from:** F001 (documented retrospectively)

---

## Decision

Data is derived from what already exists wherever a real relationship
exists. Randomness decides **attributes**, never **existence** or
**identity**.

A generator that needs a customer, a product, or a category takes the one its
input already points at. It does not reach into the master data pools and
pick.

---

## Why

A simulator that samples independently produces data that is referentially
valid and behaviourally meaningless: a customer whose sessions are in one
country and whose addresses are in another, a search for "Gaming Laptop"
returning a coffee table, a cart holding a product nobody ever looked at.

Every such incoherence is invisible to foreign key validation and obvious to
anyone reading the data.

---

## The test

Removing all randomness from a generator should still leave every foreign key
valid and every row attributable to a real parent. If it would not, the
generator is sampling something it should be deriving.

---

## Where it is applied

| Feature | Derived | Sampled |
| --- | --- | --- |
| F001 | State belongs to its country; product price band from its top-level category | Company names, coordinates, capacities |
| F002 | Address geography, language, currency and timezone all from one home city | Names, contact details, verification flags |
| F003.1 | Session location from the customer's primary address | Device, browser, traffic source |
| F003.2 | Search category inherited from the category view; vocabulary keyed by that category | Search phrase, result count |
| F003.3 | Product drawn from the browsed category's subtree; wishlist product copied from the view | Popularity weighting, dwell time |
| F004 | Cart item product copied from its product view or wishlist entry | Quantity, cart status |
| F005 | Subtotal summed from the cart; customer and session copied from the cart | Shipping method, payment method, tax rate |

F001 is the deliberate exception: master data has no transactional parent, so
products, brands, and suppliers are generated rather than derived. Even there,
countries and their subdivisions are real reference data rather than invented.

---

## Relationship to later ADRs

- **ADR-002** states the same principle from the behavioural side: derived
  data is what makes the causal chain real rather than coincidental.
- **ADR-009** restates this decision scoped to the commerce chain, where the
  entities are orders, payments, shipments, and reviews. It adds no new rule;
  it names the parents for those specific entities.
- **ADR-007** is stronger where the two overlap: a monetary value is not
  merely derived from the parent, it is *copied* from the checkout.
