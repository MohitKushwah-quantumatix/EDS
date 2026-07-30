# ADR-010 - State History Preferred Over Mutable State

**Status:** Accepted

**Applies from:** F006

---

## Decision

When a business object changes state over time, record a **history table**
rather than repeatedly updating a single status field.

The parent keeps its current status; the history keeps how it got there.

```
orders.parquet                current_status
order_status_history.parquet  history_id, order_id, status, sequence,
                              status_timestamp
```

The same approach applies later to payment status, shipment status, and
return status.

---

## Consequences

Two facts must agree and both must be validated:

- The parent's current status equals the status of its latest history row.
- History rows are ordered, contiguous, and never move backwards in time.

A history table also makes the lifecycle explicit rather than implied. F006's
suggested lifecycle - `CREATED`, `CONFIRMED`, `PROCESSING`, `PACKED`,
`SHIPPED`, `DELIVERED` - is a path, and not every order must walk all of it.
An order that stops at `PROCESSING` has three history rows and a
`current_status` of `PROCESSING`.

---

## Current state

Nothing in F000 to F005 uses a history table. Two datasets carry a single
mutable status field:

| Dataset | Field | Feature |
| --- | --- | --- |
| `shopping_carts` | `cart_status` | F004 |
| `checkout` | `checkout_status` | F005 |

Both are frozen under ADR-006 and are **not** retrofitted. A cart's or
checkout's status remains a single field; only entities introduced from F006
onward carry history.

If cart or checkout history is wanted later, it belongs in a new dataset
alongside the frozen one - `cart_status_history` - not as a change to either.

---

## `changed_by` was dropped

An earlier draft of the F006 recommendation included a `changed_by` column.
It has been removed: there is no user, operator, warehouse, employee, or actor
entity anywhere in the simulator, so the column had no upstream source and
could only have been invented.

The planned shape is therefore:

| Field |
| --- |
| `history_id` |
| `order_id` |
| `status` |
| `sequence` |
| `status_timestamp` |

If an actor entity is introduced later, `changed_by` becomes a foreign key to
it and can be added then - as a new column on a not-yet-frozen dataset, or as
a new dataset if `order_status_history` is frozen by that point.
