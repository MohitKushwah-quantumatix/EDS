# F003.3 – Product Views & Wishlist Simulator

**Feature ID:** F003.3

**Feature Name:** Product Views & Wishlist Simulator

**Capability:** Customer Journey

**Status:** Complete

---

# Objective

Implement realistic customer product browsing behaviour, extending the journey
after category browsing and searching. Generate product views and wishlists.

It must **not** generate shopping carts, checkout, orders, payments, or
reviews. Those belong to later features.

---

# Dependencies

Read existing datasets; never regenerate them.

| Feature | Datasets |
| --- | --- |
| F001 | `products`, `categories` |
| F002 | `customers` |
| F003.1 | `customer_personas`, `sessions` |
| F003.2 | `category_views`, `search_history` |

---

# Output Datasets

- `product_views.parquet`
- `wishlists.parquet`

---

# Product Views

Fields: `product_view_id`, `session_id`, `customer_id`, `category_view_id`,
`search_id`, `category_id`, `product_id`, `view_sequence`, `view_source`,
`view_duration_seconds`, `timestamp`, `created_at`

## Business rules

- Every product view belongs to an existing session, customer, and category
  view.
- The product must belong to the same category as the category view.
- `search_id` is nullable, populated only when the view originated from a
  search.
- `view_sequence` starts from 1 within each session.
- `view_duration_seconds` is between 5 and 600, averaging approximately 45.
- Per category view: 1 to 8 product views, averaging 3.

## View source

| Source | Share |
| --- | --- |
| Category | 55% |
| Search | 25% |
| Recommendation | 10% |
| Promotion | 5% |
| Brand Page | 5% |

When `view_source` is Search, `search_id` must reference an existing
`search_history` row, the search category must match the product category, and
the viewed product should be consistent with the search text where practical.

## Persona behaviour

| Persona | Behaviour |
| --- | --- |
| Researcher | Highest number of product views, longest duration |
| Window Shopper | Many product views, moderate duration |
| Bargain Hunter | Frequently enters from Promotion, high comparison |
| Loyal Customer | Frequently returns to familiar brands, moderate views |
| Impulse Buyer | Few views, short duration |
| Seasonal Shopper | Lowest activity |

## Product popularity

Products are not selected uniformly. Weighted popularity applies:

| Segment | Share of views |
| --- | --- |
| Top 20% of products | 70% |
| Next 30% | 20% |
| Remaining 50% | 10% |

Use the existing product master data. Do not modify `products.parquet`.

---

# Wishlists

Fields: `wishlist_id`, `customer_id`, `product_view_id`, `product_id`,
`added_from_source`, `timestamp`, `created_at`

## Business rules

- Entries must originate from an existing product view.
- Do not generate random wishlist products.
- A customer may add the same product only once.
- Wishlist probability depends on persona: Researcher highest, Window Shopper,
  Bargain Hunter and Loyal Customer medium, Impulse Buyer low, Seasonal
  Shopper lowest.
- Approximately 8–12% of customers create at least one wishlist.

---

# Timeline Rules

```
Customer Registration -> Session -> Category View -> Search (optional)
    -> Product View -> Wishlist (optional)
```

Chronology must never be violated. A wishlist timestamp must be after the
related product view.

---

# Data Quality Rules

Every product view references an existing session, customer, category view,
category, and product. Every wishlist references an existing customer, product
view, and product. No duplicate IDs, no timestamp outside the session, no
negative durations.

---

# Validation

Check duplicate `product_view_id` and `wishlist_id`, invalid customer,
session, `category_view`, search and product references, product/category
mismatch, search/category mismatch, wishlist without a product view, duplicate
wishlist product per customer, and the timeline.

---

# CLI

Extend `eds generate journey`. It now produces `customer_personas.parquet`,
`sessions.parquet`, `category_views.parquet`, `search_history.parquet`,
`product_views.parquet`, and `wishlists.parquet`. No new command is
introduced.

---

# Default Development Scale

1000 customers, producing approximately 5,500–6,500 sessions,
28,000–32,000 category views, 10,000–14,000 searches, 80,000–90,000 product
views, and 800–1,500 wishlist entries.

---

# Out of Scope

Shopping cart, checkout, orders, payments, shipments, returns, reviews,
recommendation engine, fraud detection.

---

# Acceptance Criteria

Both datasets generated; every product view references an existing session and
customer; every product belongs to the referenced category; search-originated
views reference a valid search; wishlist entries originate from existing
product views; duplicate wishlist products per customer are prevented;
timeline and referential integrity validation pass; CLI works; unit tests,
Ruff, and MyPy pass; output deterministic.
