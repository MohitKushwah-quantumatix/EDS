# ADR-007 - Single Source of Financial Truth

**Status:** Accepted

**Applies from:** F006

---

## Decision

Financial values are calculated once. The authoritative source is
**checkout**:

| Field |
| --- |
| `subtotal` |
| `shipping_cost` |
| `tax_amount` |
| `discount_amount` |
| `total_amount` |

- Orders reuse these values.
- Payments reuse these values.
- Shipments never recalculate them.
- Returns reference them.

Totals are never recomputed downstream.

---

## Consequences

An order carries the checkout's figures rather than re-summing its own lines.
If an order's line totals and its header total disagree, the header is right
and the lines are the defect - not the other way round.

This constrains F006: `order_lines.line_total` is a per-line breakdown, but
the order header's money must come from the checkout. Where the two cannot
agree exactly, the discrepancy belongs in the reconciliation, not in a second
calculation.

A downstream feature that needs a figure the checkout does not carry - a
per-line tax, say - must derive it from a checkout field by an explicit,
documented rule, not invent it.

---

## Current state

F005 computes all five fields, rounding each to the cent before forming the
total, and its validator recomputes the subtotal independently from
`cart_items`. Nothing downstream exists yet, so nothing currently violates
this.

---

## Resolved before F006

An earlier version of this ADR flagged a tension: F005's `subtotal` summed
**every** cart item, including ones the customer had removed before checking
out.

That was ruled a correctness bug and fixed - the exception ADR-006 allows.
The rule is now:

```
subtotal = SUM(cart items WHERE removed_at IS NULL)
```

`tax_amount` and `total_amount` derive from that corrected figure, and the
validator recomputes it the same way. A cart whose items were all removed has
a subtotal of zero and is charged shipping alone.

F006 can therefore reuse the checkout's figures directly, with no
reinterpretation needed.
