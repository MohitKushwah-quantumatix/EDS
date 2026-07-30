# ADR-012 - Business Document Immutability

**Status:** Accepted

**Applies from:** F006

---

## Decision

A business document is immutable once created. Orders, invoices, returns, and
payments are never modified after the row is written.

Business progression is represented through a separate history dataset:

```
orders.parquet                current_status
order_status_history.parquet  the transitions that led to it
```

Payments, shipments, and returns follow the same architecture.

---

## Why

A business document is a record of what was agreed at a moment in time. An
order is what the customer ordered; overwriting it loses the fact that
anything changed and leaves no way to answer when, or from what.

The simulator has a second reason: a mutable document has no single correct
value to validate against. A history table gives every state a timestamp and a
sequence, so "was this valid" becomes a question about an ordered series
rather than about a field that has already been overwritten.

---

## What "immutable" means here

The simulator writes each dataset once, so nothing is literally updated in
place. The rule is about **design**, not about the write path: a document must
not carry a field whose meaning is "the latest value of something that
changes".

`current_status` is the deliberate exception, and it is a denormalised
convenience rather than the source of truth. It must always equal the status
of the document's latest history row, and that agreement is validated.

---

## Relationship to ADR-010

ADR-010 says state changes go in a history table. This ADR says the document
they belong to is frozen.

They are two halves of the same decision, and a feature needs both: without
ADR-010 there is nowhere for the progression to live, and without this ADR
there is nothing stopping a later feature from adding a mutable field back
onto the document.

---

## Consequences for F006

An order is written once. `orders.current_status` is derived from
`order_status_history`, not the other way round, and two rules must hold:

- every order's `current_status` equals the status of its latest history row;
- history rows are ordered, contiguous, and never move backwards in time.

Not every order reaches `DELIVERED`. An order that stops at `PROCESSING` has
three history rows and a `current_status` of `PROCESSING` - it is complete
data, not missing data.

---

## Current state

Nothing in F000 to F005 has a history dataset. `shopping_carts.cart_status`
and `checkout.checkout_status` are single fields, frozen under ADR-006 and
deliberately not retrofitted. If cart or checkout history is wanted later it
belongs in a new dataset beside the frozen one.
