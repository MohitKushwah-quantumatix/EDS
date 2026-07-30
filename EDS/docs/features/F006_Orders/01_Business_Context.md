# F006 – Orders Simulator

**Feature ID:** F006

**Feature Name:** Orders Simulator

**Capability:** Commerce

**Status:** Complete

---

# Objective

Generate immutable business documents representing customer orders. Orders are
created only from successful checkouts.

Generate `orders.parquet`, `order_lines.parquet`, and
`order_status_history.parquet`. Do not generate payments, shipments, returns,
or reviews.

---

# Dependencies

Read only existing datasets; never regenerate them.

| Feature | Datasets |
| --- | --- |
| F001 | `products` |
| F002 | `customers`, `customer_addresses` |
| F004 | `shopping_carts`, `cart_items` |
| F005 | `checkout` |

---

# Orders

Fields: `order_id`, `order_number`, `checkout_id`, `cart_id`, `customer_id`,
`session_id`, `shipping_address_id`, `billing_address_id`, `current_status`,
`subtotal`, `shipping_cost`, `tax_amount`, `discount_amount`, `total_amount`,
`order_date`, `created_at`

## Order number

Format `ORD-YYYYMMDD-000001`. Unique, sequential, deterministic, never reused.

## Business rules

- Only `checkout_status = SUCCESS` creates an order.
- FAILED and ABANDONED checkouts create no order.
- Exactly one order per successful checkout.
- Orders are immutable.
- Financial values are copied from the checkout. Never recalculate the
  subtotal, shipping, tax, discount, or total.

---

# Order Lines

Fields: `order_line_id`, `order_id`, `product_id`, `quantity`, `unit_price`,
`line_total`, `created_at`

## Business rules

- Lines originate only from **active** cart items belonging to the order's
  cart. Removed cart items are ignored.
- `line_total` = `quantity` × `unit_price`.
- Order totals must reconcile with the order lines.

---

# Order Status History

Fields: `history_id`, `order_id`, `status`, `sequence`, `status_timestamp`

Current status is stored in `orders.parquet`; the transitions live here.

## Default lifecycle

| Status | Share of orders |
| --- | --- |
| CREATED | 100% |
| CONFIRMED | 95% |
| PROCESSING | 90% |

Not every order continues. `PACKED`, `SHIPPED` and `DELIVERED` belong to
future features and are not generated yet.

---

# Timeline

```
Customer Registration -> Session -> Product View -> Cart -> Checkout
    -> Order -> Order Status History
```

All timestamps must be chronological.

---

# Data Quality

Every order references an existing checkout, cart, customer, session, and
addresses. Every order line references an existing order and product. Every
status history row references an existing order. Financial values must
reconcile.

---

# Validation

Check duplicate `order_id`, `order_number`, `order_line_id` and `history_id`;
invalid checkout, cart, customer, address and product references; subtotal
mismatch; order line total mismatch; one order per checkout; the timeline; and
the history sequence.

---

# CLI

`eds generate commerce` now produces `shopping_carts.parquet`,
`cart_items.parquet`, `checkout.parquet`, `orders.parquet`,
`order_lines.parquet`, and `order_status_history.parquet`. No new CLI commands
are added.

---

# Expected Development Scale

1000 customers, producing approximately 300–350 orders, 600–900 order lines,
and 900–1100 status history rows.

---

# Out of Scope

Payments, shipments, returns, reviews, inventory reservation, invoices,
refunds, fraud detection.

---

# Acceptance Criteria

All three datasets generated; orders originate only from SUCCESS checkouts;
one order per checkout; financial values copied from the checkout; order lines
reconcile with totals; removed cart items excluded; order numbers
deterministic; status history chronological; validation, CLI, unit tests, Ruff
and MyPy all pass; output deterministic.
