# F005 – Checkout Simulator

**Feature ID:** F005

**Feature Name:** Checkout Simulator

**Capability:** Commerce

**Status:** Complete

---

# Objective

Implement realistic checkout behaviour, converting shopping carts into
checkout attempts. Generate `checkout.parquet`.

It must **not** generate orders, payments, shipments, returns, or reviews.
Orders belong to F006.

---

# Dependencies

Read existing datasets; never regenerate them.

| Feature | Datasets |
| --- | --- |
| F001 | `products` |
| F002 | `customers`, `customer_addresses` |
| F003.1 | `sessions` |
| F004 | `shopping_carts`, `cart_items` |

---

# Output Dataset

- `checkout.parquet`

---

# Checkout

Fields: `checkout_id`, `cart_id`, `customer_id`, `session_id`,
`shipping_address_id`, `billing_address_id`, `shipping_method`,
`payment_method`, `checkout_status`, `subtotal`, `shipping_cost`,
`tax_amount`, `discount_amount`, `total_amount`, `started_at`,
`completed_at`, `created_at`

## Checkout status

| Status | Share |
| --- | --- |
| SUCCESS | 82% |
| FAILED | 8% |
| ABANDONED | 10% |

## Business rules

- Only carts with `cart_status = CHECKED_OUT` are eligible.
- Each eligible cart generates exactly one checkout.
- ACTIVE and ABANDONED carts must not generate a checkout.

## Address selection

Both `shipping_address_id` and `billing_address_id` must reference an existing
customer address. If the customer has only one address, shipping and billing
may be identical.

## Shipping method

| Method | Share | Cost |
| --- | --- | --- |
| STANDARD | 70% | 0–8 |
| EXPRESS | 20% | 8–20 |
| NEXT_DAY | 5% | 20–35 |
| STORE_PICKUP | 5% | 0 |

## Payment method

| Method | Share |
| --- | --- |
| UPI | 35% |
| CREDIT_CARD | 25% |
| DEBIT_CARD | 15% |
| COD | 10% |
| NET_BANKING | 10% |
| WALLET | 5% |

## Order value

- `subtotal` = sum of `cart_item.quantity × unit_price`
- `tax_amount` = 5–18%
- `discount_amount` = 0 unless future features introduce promotions
- `total_amount` = `subtotal` + `shipping_cost` + `tax_amount` −
  `discount_amount`

---

# Timeline

```
Customer Registration -> Session -> Product View -> Cart
    -> Checkout Started -> Checkout Completed
```

`completed_at` must be after `started_at`.

| Status | `completed_at` |
| --- | --- |
| SUCCESS | populated |
| FAILED | populated |
| ABANDONED | NULL |

---

# Data Quality Rules

Every checkout references an existing cart, customer, session, and addresses.
Only CHECKED_OUT carts generate a checkout. Totals must reconcile.

---

# Validation

Check duplicate `checkout_id`, invalid customer, cart, session and address
references, subtotal mismatch, total mismatch, the timeline, one checkout per
cart, and invalid cart status.

---

# CLI

`eds generate commerce` now generates `shopping_carts.parquet`,
`cart_items.parquet`, and `checkout.parquet`. No additional commands are
introduced.

---

# Default Development Scale

1000 customers, producing approximately 330–420 checkout records.

---

# Out of Scope

Orders, payments, shipments, returns, reviews, inventory reservation,
promotion engine, fraud detection.

---

# Acceptance Criteria

`checkout.parquet` generated; every checkout references an existing cart,
customer, session, and valid customer addresses; only CHECKED_OUT carts
generate a checkout; `subtotal` and `total_amount` are correct; timeline and
referential integrity validation pass; CLI works; unit tests, Ruff, and MyPy
pass; output deterministic.
