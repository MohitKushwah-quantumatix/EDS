# ADR-011 - One Dataset Per Business Entity

**Status:** Accepted

**Applies from:** F006

---

## Decision

Prefer normalised datasets. A parent and its collection are separate
datasets.

| Parent | Collection |
| --- | --- |
| `shopping_carts` | `cart_items` |
| `orders` | `order_lines` |
| `shipments` | `shipment_items` |
| `returns` | `return_items` |

Repeated collections are never stored inside a parent record.

---

## Consequences

A parent may carry a denormalised count of its children - `item_count` on
`shopping_carts` - provided the count is derived from the children and
validated against them, never asserted alongside them.

The generation order this implies is: plan the parents, generate the children,
then finalise the parents from what the children actually became. Generating
the parent's aggregate first and hoping the children match is what this ADR
rules out.

---

## Current state

Already followed. F004 splits `shopping_carts` from `cart_items` and derives
`item_count` from the items rather than declaring it up front - the F004
review records this as a design decision, and a validation rule fails if the
count and the rows disagree.

F006 extends the same shape twice over: `orders` with `order_lines` for the
collection, and `order_status_history` for the lifecycle.

---

## Interaction with ADR-010

The two ADRs pull an order into three datasets for different reasons:

- `order_lines` because a collection is not stored inside its parent
  (this ADR).
- `order_status_history` because state over time is not a mutable field
  (ADR-010).

Neither belongs inside `orders.parquet`.
