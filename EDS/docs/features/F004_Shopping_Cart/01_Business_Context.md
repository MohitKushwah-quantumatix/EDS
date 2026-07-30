# F004 – Shopping Cart Simulator

**Feature ID:** F004

**Feature Name:** Shopping Cart Simulator

**Capability:** Commerce

**Status:** Complete

---

# Objective

Implement realistic shopping cart behaviour, converting customer browsing into
purchase intent. Generate shopping carts and cart items.

It must **not** generate checkout, orders, payments, shipments, returns, or
reviews. Those belong to later features.

---

# Dependencies

Read existing datasets; never regenerate them.

| Feature | Datasets |
| --- | --- |
| F001 | `products` |
| F002 | `customers` |
| F003.1 | `sessions`, `customer_personas` |
| F003.3 | `product_views`, `wishlists` |

---

# Output Datasets

- `shopping_carts.parquet`
- `cart_items.parquet`

---

# Shopping Carts

Fields: `cart_id`, `customer_id`, `session_id`, `cart_status`, `item_count`,
`created_at`, `updated_at`

## Cart status

| Status | Share |
| --- | --- |
| ABANDONED | 55% |
| CHECKED_OUT | 40% |
| ACTIVE | 5% |

## Business rules

- Every cart belongs to exactly one customer and one session.
- A customer may have multiple carts; a session may have zero or one.
- Every cart contains at least one item.
- `item_count` equals the number of cart items.
- `updated_at` must be after `created_at`.

## Cart size

| Items | Share |
| --- | --- |
| 1 | 55% |
| 2 | 25% |
| 3 | 12% |
| 4 | 5% |
| 5+ | 3% |

---

# Cart Items

Fields: `cart_item_id`, `cart_id`, `customer_id`, `product_id`,
`product_view_id`, `wishlist_id`, `quantity`, `unit_price`, `added_from`,
`added_at`, `removed_at`

## Business rules

- Every item references an existing cart, customer, product, and product view.
- `wishlist_id` is nullable, populated only when the product came from a
  wishlist.
- `added_from` is `PRODUCT_VIEW` or `WISHLIST`.
- An item must originate from an existing product view or wishlist entry.
  Never generate random products.

## Product selection

If `added_from` is `PRODUCT_VIEW`, `product_id` must equal the referenced
product view's product. If `added_from` is `WISHLIST`, it must equal the
referenced wishlist entry's product.

## Quantity

| Quantity | Share |
| --- | --- |
| 1 | 70% |
| 2 | 18% |
| 3 | 7% |
| 4 | 3% |
| 5 | 2% |

---

# Persona behaviour

| Persona | Behaviour |
| --- | --- |
| Researcher | Largest carts, frequently wishlists before cart |
| Window Shopper | Occasional carts, mostly abandoned |
| Bargain Hunter | Higher cart rate, frequently promotion-driven |
| Loyal Customer | Highest checkout probability, moderate cart size |
| Impulse Buyer | Small carts, high checkout probability, rare wishlist |
| Seasonal Shopper | Lowest activity |

---

# Timeline

```
Customer Registration -> Session -> Category View -> Search (optional)
    -> Product View -> Wishlist (optional) -> Shopping Cart -> Cart Item
```

Chronology must never be violated. `added_at` must occur after the referenced
product view or wishlist entry. `removed_at` is nullable; when populated it
must be after `added_at`.

---

# Data Quality Rules

Every cart references an existing customer and session. Every cart item
references an existing cart, customer, product, and product view. Wishlist
references must exist when populated. No duplicate IDs, no negative quantity,
no timestamp before its source event.

---

# Validation

Check duplicate `cart_id` and `cart_item_id`, invalid customer, session, cart,
product, product view, and wishlist references, product mismatch, negative
quantity, invalid timestamps, and `item_count` mismatch.

---

# CLI

`eds generate commerce` produces `shopping_carts.parquet` and
`cart_items.parquet`. It does not regenerate previous datasets, and no
additional commands are introduced.

---

# Default Development Scale

1000 customers, producing 700–1000 shopping carts and 1500–2500 cart items.

---

# Out of Scope

Checkout, orders, payments, taxes, coupons, inventory reservation, shipping
charges, discount engine, returns, reviews, recommendation engine, fraud
detection.

---

# Acceptance Criteria

Both datasets generated; every cart references an existing customer and
session; every cart item references an existing cart, product, and product
view; wishlist-originated items reference a valid wishlist; product IDs always
match their originating product view or wishlist; `item_count` equals the
number of cart items; timeline and referential integrity validation pass; CLI
works; unit tests, Ruff, and MyPy pass; output deterministic.
