# F008 – Shipment Simulator

**Feature ID:** F008

**Feature Name:** Shipment Simulator

**Capability:** Commerce / Supply Chain

**Status:** Complete

---

# Objective

Generate shipment business documents. A shipment is the physical side of an
order, and it exists only where the money actually moved: shipments originate
**only** from successfully captured payments.

Generate `shipments.parquet`, `shipment_items.parquet`, and
`shipment_status_history.parquet`. Do not generate returns or reviews.

---

# Dependencies

Read only existing datasets; never regenerate them.

| Feature | Datasets |
| --- | --- |
| F001 | `products` |
| F002 | `customers` |
| F005 | `checkout` |
| F006 | `orders`, `order_lines` |
| F007 | `payments` |

The checkout is read for one column: `shipping_method`. Neither the order nor
the payment carries it, and the carrier depends on it.

---

# Shipments

Fields: `shipment_id`, `shipment_number`, `order_id`, `payment_id`,
`customer_id`, `carrier`, `shipping_method`, `tracking_number`,
`current_status`, `shipped_at`, `estimated_delivery_at`, `delivered_at`,
`created_at`

## Shipment number

Format `SHP-YYYYMMDD-000001`. Unique, sequential within a day, deterministic.

## Tracking number

Format `TRK-XXXXXXXXXX`. Unique and deterministic — derived from the shipment
identifier by a modular scramble that is a bijection, so collisions are
impossible rather than merely unlikely.

## Carrier

Read from `shipments.yaml` and selected by shipping method:

| Method | Carriers |
| --- | --- |
| `STANDARD` | UPS, FedEx, DHL |
| `EXPRESS` | FedEx Priority, DHL Express |
| `NEXT_DAY` | UPS Next Day |
| `STORE_PICKUP` | Store Pickup |

## Shipment eligibility

| Payment status | Shipment |
| --- | --- |
| `CAPTURED` | Exactly one |
| `FAILED` | None |
| `VOIDED` | None |

## Business rules

- Shipments originate only from captured payments.
- Exactly one shipment per captured payment.
- `shipping_method` is copied from the checkout the order came from.
- `carrier` is chosen from the carriers that method offers.
- Shipments are immutable.

---

# Shipment Items

Fields: `shipment_item_id`, `shipment_id`, `order_line_id`, `product_id`,
`quantity`, `created_at`

## Business rules

- Shipment items originate only from order lines.
- Every line of a shipped order goes out: split shipments and backorders are
  out of scope, so an order line ships exactly once.
- `quantity` and `product_id` are copied from the order line.
- Products are never regenerated.

---

# Shipment Status History

Fields: `history_id`, `shipment_id`, `status`, `sequence`, `status_timestamp`

## Lifecycle

```
CREATED → PACKED → SHIPPED → IN_TRANSIT → DELIVERED
```

Completion shares: `DELIVERED` 90%, `IN_TRANSIT` 7%, `SHIPPED` 3%. They sum to
100%, so every shipment reaches at least `SHIPPED`.

`RETURNED`, `LOST` and `DAMAGED` belong to later features and are deliberately
absent from the enum.

## Business rules

- Every shipment has at least three status rows.
- `sequence` starts at one and is contiguous per shipment.
- Timestamps advance with the sequence, and so does lifecycle position.
- `shipments.current_status` equals the status of the latest history row, and
  `shipped_at` / `delivered_at` equal the timestamps of their history rows
  (ADR-010, ADR-012).

---

# Timeline

```
Order → Payment → Shipment Created → Packed → Shipped → In Transit → Delivered
```

`delivered_at` must be after `shipped_at`. Every timestamp is chronological.

## Estimated delivery

Promised when the shipment is created, from the method's day range:

| Method | Days |
| --- | --- |
| `STANDARD` | 3–7 |
| `EXPRESS` | 1–3 |
| `NEXT_DAY` | 1 |
| `STORE_PICKUP` | Same day |

---

# Configuration

[`configs/shipments.yaml`](../../../configs/shipments.yaml)

| Setting | Default | Meaning |
| --- | --- | --- |
| `carriers` | see above | Carriers offered per shipping method |
| `delivery_days` | see above | Promised `(min, max)` days per method |
| `shipment_lead_seconds` | `1` | Payment captured to shipment created |
| `delivered_rate` | `0.90` | Share reaching `DELIVERED` |
| `in_transit_rate` | `0.07` | Share stopping at `IN_TRANSIT` |
| `shipped_rate` | `0.03` | Share stopping at `SHIPPED` |
| `min_pack_minutes` / `max_pack_minutes` | `30` / `1440` | Creation to packing |
| `min_dispatch_minutes` / `max_dispatch_minutes` | `60` / `1440` | Packing to dispatch |
| `min_transit_hours` / `max_transit_hours` | `2` / `48` | Dispatch to in transit |
| `min_delivery_hours` / `max_delivery_hours` | `4` / `120` | In transit to delivery |
| `shipment_number_prefix` | `SHP` | Leading token of the shipment number |
| `tracking_number_prefix` | `TRK` | Leading token of the tracking number |
| `batch_size` | `100000` | Rows generated per batch |

The three completion shares must sum to `1.0`.

---

# Command

No new command. `eds generate commerce` now produces eleven datasets: carts
and cart items (F004), checkouts (F005), orders with lines and status history
(F006), payments with status history (F007), and shipments with items and
status history (F008).

---

# Out of scope

Returns, lost packages, damage claims, split shipments, backorders, multiple
warehouses, international customs, carrier APIs, and shipment retries.
