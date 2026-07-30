# F003.2 – Category Browsing & Search Simulator

**Feature ID:** F003.2

**Feature Name:** Category Browsing & Search Simulator

**Capability:** Customer Journey

**Status:** Complete

---

# Objective

Implement realistic customer browsing behaviour, extending the customer
journey after a browsing session has been created. For every existing session,
simulate category browsing and customer searches.

It must **not** generate product views, wishlists, shopping carts, orders,
payments, or reviews. Those belong to later features.

---

# Dependencies

Read existing datasets; never regenerate them.

| Feature | Datasets |
| --- | --- |
| F001 | `categories`, `products` |
| F002 | `customers` |
| F003.1 | `customer_personas`, `sessions` |

---

# Output Datasets

- `category_views.parquet`
- `search_history.parquet`

---

# Category Views

Fields: `category_view_id`, `session_id`, `customer_id`, `category_id`,
`view_sequence`, `entry_method`, `timestamp`, `duration_seconds`, `created_at`

## Business rules

- Each session generates 1–10 category views, averaging approximately 5.
- Every category must exist in `categories.parquet`.
- Category timestamps must fall within the session.
- `view_sequence` starts from 1.
- `duration_seconds` is between 5 and 180.

## Entry methods

Homepage, Navigation Menu, Promotion Banner, Search Result, Recommendation,
Brand Page.

## Persona behaviour

| Persona | Category views | Browsing character |
| --- | --- | --- |
| Researcher | 6–10 | Longest browsing duration |
| Window Shopper | 5–8 | Moderate duration |
| Bargain Hunter | 4–7 | Promotion Banner preferred |
| Loyal Customer | 3–6 | Frequently starts from Homepage |
| Impulse Buyer | 1–3 | Very short duration |
| Seasonal Shopper | 1–4 | Lower activity |

---

# Search History

Fields: `search_id`, `session_id`, `customer_id`, `category_view_id`,
`category_id`, `search_sequence`, `search_text`, `results_count`,
`clicked_result`, `timestamp`, `created_at`

## Business rules

- Each session performs 0–10 searches, averaging approximately 2.
- Searches occur after the first category view.
- Search timestamps must fall within the session.
- `search_sequence` starts from 1.
- `results_count` is between 0 and 250.
- `clicked_result` is true or false.

## Category to search consistency

Every search must relate to the category currently being viewed.

| Category | Example searches |
| --- | --- |
| Electronics | Gaming Laptop, Wireless Mouse, Mechanical Keyboard, Bluetooth Speaker, USB-C Charger |
| Furniture | Office Chair, Standing Desk, Coffee Table, Bookshelf |
| Fashion | Running Shoes, T-Shirt, Jeans, Sneakers, Jacket |
| Home & Kitchen | Coffee Machine, Mixer Grinder, Cookware Set, Water Bottle, Dining Table |
| Sports | Cricket Bat, Football, Tennis Racket, Gym Bag, Yoga Mat |

Unrelated searches are not allowed: Electronics must never produce "Coffee
Table".

## Search generation

Realistic, product-oriented phrases of one to four words. No random words.

---

# Timeline Rules

```
Customer Registration -> Session Start -> Category View -> Search -> Session End
```

Chronology must never be violated.

---

# Data Quality Rules

Every category view references an existing session, customer, and category.
Every search references an existing session, customer, category view, and
category. No duplicate IDs, no timestamp outside its session, no negative
duration, no invalid sequence numbers.

---

# Validation

Check duplicate `category_view_id`, duplicate `search_id`, invalid customer,
session, category and `category_view` references, timestamps outside the
session, invalid view and search sequences, negative duration, and category
mismatch between a search and its category view.

---

# CLI

Extend `eds generate journey`. It now produces `customer_personas.parquet`,
`sessions.parquet`, `category_views.parquet`, and `search_history.parquet`.
No new command is introduced.

---

# Default Development Scale

1000 customers, producing approximately 5,500–6,500 sessions,
28,000–32,000 category views, and 10,000–14,000 searches.

---

# Out of Scope

Product views, wishlist, shopping cart, checkout, orders, payments, shipments,
returns, reviews, recommendation engine, fraud detection.

---

# Acceptance Criteria

Both datasets generated; every category view references an existing session,
customer, and category; every search references an existing session, customer,
category view, and category; every search belongs to the same category as its
category view; timeline and referential integrity validation pass; CLI works;
unit tests, Ruff, and MyPy pass; output deterministic.
