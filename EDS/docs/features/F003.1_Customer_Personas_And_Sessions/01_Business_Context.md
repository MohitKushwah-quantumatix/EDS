# F003.1 – Customer Personas & Session Simulator

**Feature ID:** F003.1

**Feature Name:** Customer Personas & Session Simulator

**Capability:** Customer Journey

**Status:** Complete

---

# Objective

Implement the first phase of the Digital Customer Journey: realistic customer
personas and browsing sessions. This is the foundation for every future
customer interaction.

It does **not** generate category browsing, searches, product views,
wishlists, shopping carts, or orders. Those belong to later features.

---

# Dependencies

Read existing datasets; never regenerate them.

| Feature | Datasets |
| --- | --- |
| F001 | `countries`, `states`, `cities`, `products`, `categories` |
| F002 | `customers`, `customer_addresses`, `customer_preferences`, `customer_loyalty` |

---

# Output Datasets

- `customer_personas.parquet`
- `sessions.parquet`

---

# Customer Personas

Every customer receives exactly one persona.

Fields: `persona_id`, `customer_id`, `persona_name`, `purchase_intent`,
`price_sensitivity`, `brand_loyalty`, `research_depth`, `session_frequency`,
`average_session_minutes`, `wishlist_probability`, `cart_probability`,
`purchase_probability`, `description`, `created_at`

## Supported personas and behaviour profiles

| Persona | Share | Sessions | Average duration | Description |
| --- | --- | --- | --- | --- |
| Window Shopper | 25% | 5–15 | 10–20 min | Visits frequently, looks around, rarely purchases |
| Researcher | 20% | 10–20 | 20–45 min | Long sessions, many comparisons, very analytical |
| Bargain Hunter | 20% | 6–15 | 10–25 min | Searches extensively, responds to discounts, price conscious |
| Loyal Customer | 20% | 4–10 | 8–18 min | Returns regularly, familiar brands, high purchase likelihood |
| Impulse Buyer | 10% | 1–5 | 2–8 min | Very short decision cycle, few page views, quick purchase |
| Seasonal Shopper | 5% | 0–5 | 5–15 min | Mostly inactive, highly active during holidays |

---

# Sessions

Fields: `session_id`, `customer_id`, `persona_name`, `device_type`, `browser`,
`operating_system`, `traffic_source`, `landing_page`, `exit_page`,
`country_id`, `state_id`, `city_id`, `ip_address`, `start_time`, `end_time`,
`duration_seconds`, `pages_viewed`, `bounce`, `created_at`

## Value domains

- **Traffic sources:** Organic Search, Paid Search, Referral, Direct, Email
  Campaign, Social Media, Display Ads
- **Devices:** Mobile 65%, Desktop 30%, Tablet 5%
- **Browsers:** Chrome, Edge, Safari, Firefox, Opera
- **Operating systems:** Android, iOS, Windows, macOS, Linux
- **Landing pages:** Homepage, Category, Search, Promotion, Brand, Campaign
- **Exit pages:** Homepage, Category, Product, Search, Promotion

## Business rules

- Each session belongs to exactly one customer.
- Session count and duration depend on the persona.
- Bounce sessions: approximately 25%.
- Pages viewed: 1 for a bounce, 2–25 otherwise.
- Landing page and exit page always exist.

## Timeline rules

- Session start must be after customer registration.
- Session end must be after session start.
- All sessions must occur within the last five years.
- Sessions should appear naturally over time, not on consecutive days.

## IP address

Realistic IPv4 addresses. Geography should match the customer's country where
practical.

---

# Validation

Check duplicate session IDs, duplicate persona IDs, invalid customer IDs,
invalid geography, session end before start, negative duration, customers
without a persona, and sessions before registration.

---

# CLI

```bash
eds generate journey
eds generate journey --seed 42
```

---

# Performance

Polars DataFrames, batch generation, no Python object per row, deterministic
output, reusing the existing random streams.

---

# Default Development Scale

1000 customers, producing approximately 6000 sessions and 1000 personas.

---

# Out of Scope

Category views, searches, product views, wishlists, shopping cart, checkout,
orders, payments, returns, reviews, recommendation engine, fraud detection.

---

# Acceptance Criteria

Both datasets generated; every customer has exactly one persona; every session
references an existing customer; session timestamps valid; sessions start
after registration; validation passes; CLI works; unit tests, Ruff, and MyPy
pass; output deterministic.
