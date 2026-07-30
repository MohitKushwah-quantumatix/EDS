# F009 – Returns Simulator

**Feature ID:** F009

**Feature Name:** Returns Simulator

**Capability:** Commerce / Reverse Logistics

**Status:** Complete

---

# Objective

Generate realistic customer return requests. A return is the reverse journey,
and it starts where the forward one ended: returns originate **only** from
delivered shipment items.

Generate `returns.parquet`, `return_items.parquet`, and
`return_status_history.parquet`. Do not generate reviews.

---

# Dependencies

Read only existing datasets; never regenerate them.

| Feature | Datasets |
| --- | --- |
| F001 | `products`, `return_reasons` |
| F006 | `orders`, `order_lines` |
| F008 | `shipments`, `shipment_items` |

`return_reasons` did not exist before this feature. It was added to F001 as a
fourteenth master dataset under an explicit instruction from the technical
lead — see [03_Review.md](03_Review.md).

---

# Returns

Fields: `return_id`, `return_number`, `shipment_id`, `customer_id`,
`return_reason`, `refund_type`, `current_status`, `requested_at`,
`approved_at`, `received_at`, `completed_at`, `created_at`

## Return number

Format `RET-YYYYMMDD-000001`. Unique, sequential within a day, deterministic.

## Return eligibility

| Shipment status | Return |
| --- | --- |
| `DELIVERED` | At most one, at the configured rate |
| Anything else | None |

A delivered shipment that carried no items is also ineligible: returns
originate from delivered shipment *items*, so there must be something to send
back.

## Return reasons

Read from `return_reasons.parquet`, never hardcoded. Only active reasons are
offered:

| Code | Name | Customer fault | Requires inspection |
| --- | --- | --- | --- |
| `DAMAGED` | Damaged | No | Yes |
| `WRONG_ITEM` | Wrong Item | No | Yes |
| `DEFECTIVE` | Defective | No | Yes |
| `CHANGED_MIND` | Changed Mind | Yes | No |
| `LATE_DELIVERY` | Late Delivery | No | No |

## Refund type

Read from `returns.yaml`, with a share per type:

| Type | Share |
| --- | --- |
| `FULL_REFUND` | 70% |
| `STORE_CREDIT` | 20% |
| `REPLACEMENT` | 10% |

## Business rules

- Returns originate only from delivered shipments.
- At most one return per shipment.
- `customer_id` is copied from the shipment, its single parent under ADR-008.
- Returns are immutable.

---

# Return Items

Fields: `return_item_id`, `return_id`, `shipment_item_id`, `order_line_id`,
`product_id`, `quantity`, `created_at`

## Business rules

- Return items originate only from shipment items.
- Lineage is preserved exactly: `order_line_id`, `product_id` and `quantity`
  are carried across from the shipment item untouched.
- A customer sends back between one and all of the items that arrived.
- A shipment item comes back at most once.
- Products and quantities are never regenerated.

---

# Return Status History

Fields: `history_id`, `return_id`, `status`, `sequence`, `status_timestamp`

## Lifecycle

```
REQUESTED → APPROVED → IN_TRANSIT → RECEIVED → COMPLETED
```

Completion shares: `COMPLETED` 85%, `RECEIVED` 8%, `IN_TRANSIT` 5%,
`APPROVED` 2%. They sum to 100%, so every return reaches at least `APPROVED`.

`REJECTED`, `CANCELLED` and `REFUNDED` belong to later finance extensions and
are deliberately absent from the enum.

## Business rules

- Every return has at least two status rows.
- `sequence` starts at one and is contiguous per return.
- Timestamps advance with the sequence, and so does lifecycle position.
- `returns.current_status` equals the status of the latest history row, and
  `approved_at` / `received_at` / `completed_at` equal the timestamps of their
  history rows (ADR-010, ADR-012).

---

# Timeline

```
Shipment Delivered → Return Requested → Approved → Customer Ships Item
                   → Warehouse Receives Item → Completed
```

`requested_at` must be after `shipment.delivered_at`. Every timestamp is
chronological.

---

# Configuration

[`configs/returns.yaml`](../../../configs/returns.yaml)

| Setting | Default | Meaning |
| --- | --- | --- |
| `return_rate` | `0.12` | Share of eligible delivered shipments returned |
| `refund_types` | see above | How a return is settled, and how often |
| `min_request_days` / `max_request_days` | `1` / `21` | Delivery to request |
| `completed_rate` | `0.85` | Share reaching `COMPLETED` |
| `received_rate` | `0.08` | Share stopping at `RECEIVED` |
| `in_transit_rate` | `0.05` | Share stopping at `IN_TRANSIT` |
| `approved_rate` | `0.02` | Share stopping at `APPROVED` |
| `min_approval_hours` / `max_approval_hours` | `2` / `72` | Request to approval |
| `min_dispatch_hours` / `max_dispatch_hours` | `4` / `120` | Approval to dispatch |
| `min_transit_hours` / `max_transit_hours` | `24` / `168` | Dispatch to receipt |
| `min_completion_hours` / `max_completion_hours` | `2` / `96` | Receipt to completion |
| `return_number_prefix` | `RET` | Leading token of the return number |
| `batch_size` | `100000` | Rows generated per batch |

Both the refund shares and the four lifecycle shares must sum to `1.0`. The
reason vocabulary is deliberately **not** here: it is master data.

---

# Command

No new command. `eds generate commerce` now produces fourteen datasets: carts
and cart items (F004), checkouts (F005), orders with lines and status history
(F006), payments with status history (F007), shipments with items and status
history (F008), and returns with items and status history (F009).

---

# Out of scope

Refund payments, chargebacks, replacement shipments, warranty, exchange
orders, inventory restocking, and vendor returns.
