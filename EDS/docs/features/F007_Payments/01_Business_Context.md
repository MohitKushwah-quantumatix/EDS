# F007 – Payment Processing Simulator

**Feature ID:** F007

**Feature Name:** Payment Processing Simulator

**Capability:** Commerce

**Status:** Complete

---

# Objective

Simulate payment processing for orders. A payment is the money side of an
order, and payments originate **only** from orders.

Generate `payments.parquet` and `payment_status_history.parquet`. Do not
generate refunds, chargebacks, invoices, settlement, shipments, returns, or
reviews.

---

# Dependencies

Read only existing datasets; never regenerate them.

| Feature | Datasets |
| --- | --- |
| F002 | `customers` |
| F005 | `checkout` |
| F006 | `orders` |

The checkout is read for one column: `payment_method`. The order does not
carry it, and the specification requires the method to be copied from the
checkout rather than re-drawn.

---

# Payments

Fields: `payment_id`, `payment_reference`, `order_id`, `customer_id`,
`payment_method`, `payment_provider`, `currency`, `payment_amount`,
`payment_status`, `authorized_at`, `captured_at`, `created_at`

## Payment reference

Format `PAY-YYYYMMDD-000001`. Unique, sequential within a day, deterministic,
never reused.

## Payment provider

Derived from the payment method, never sampled:

| Method | Provider |
| --- | --- |
| `UPI` | UPI Gateway |
| `CREDIT_CARD` | Stripe |
| `DEBIT_CARD` | Stripe |
| `NET_BANKING` | Bank Gateway |
| `COD` | Cash On Delivery |
| `WALLET` | Wallet Provider |

## Business rules

- Payments originate only from orders.
- Exactly one payment per payable order.
- An order billed at zero or less is not charged.
- `payment_amount` is copied from the order's `total_amount`. Never
  recalculate it.
- `payment_method` is copied from the checkout the order came from.
- `currency` is read from configuration. Never inferred.
- Payments are immutable.

---

# Payment Status History

Fields: `history_id`, `payment_id`, `status`, `sequence`, `status_timestamp`

## Lifecycle

```
AUTHORIZED → CAPTURED
AUTHORIZED → VOIDED
FAILED
```

A payment either fails outright - one row, and that is the whole story - or is
authorised and then either captured or voided. `CAPTURED`, `VOIDED` and
`FAILED` are terminal; reversing a capture is a refund, which is out of scope.

## Business rules

- Every payment has at least one status row.
- `sequence` starts at one and is contiguous per payment.
- Timestamps advance with the sequence.
- `payments.payment_status` equals the status of the latest history row
  (ADR-010, ADR-012).
- `authorized_at` is populated exactly when the payment is not `FAILED`.
- `captured_at` is populated exactly when the payment is `CAPTURED`.

---

# Configuration

[`configs/payments.yaml`](../../../configs/payments.yaml)

| Setting | Default | Meaning |
| --- | --- | --- |
| `currency` | `USD` | ISO 4217 code recorded on every payment |
| `capture_rate` | `0.92` | Share authorised and then captured |
| `void_rate` | `0.03` | Share authorised and then voided |
| `failure_rate` | `0.05` | Share that fail outright |
| `authorization_lead_seconds` | `1` | Order created to payment attempted |
| `min_capture_minutes` / `max_capture_minutes` | `1` / `180` | Wait before capture |
| `min_void_minutes` / `max_void_minutes` | `5` / `1440` | Wait before voiding |
| `payment_reference_prefix` | `PAY` | Leading token of the reference |
| `batch_size` | `100000` | Rows generated per batch |

The three outcome shares must sum to `1.0`.

---

# Command

No new command. `eds generate commerce` now produces eight datasets: carts and
cart items (F004), checkouts (F005), orders with lines and status history
(F006), and payments with status history (F007).

---

# Out of scope

Refunds, chargebacks, invoices, settlement, multi-currency, fraud detection,
payment retries, partial capture, and partial refund.
