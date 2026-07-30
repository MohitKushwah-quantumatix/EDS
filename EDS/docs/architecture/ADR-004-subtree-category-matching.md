# ADR-004 - Subtree Category Matching

**Status:** Accepted

**Applies from:** F003.3 (documented retrospectively)

---

## Decision

Category containment is decided by **subtree matching**, not exact equality.

A product belongs to a category when the product's own category is that
category **or any descendant of it**. Containment is tested by category path:

```
product_path == browsed_path
or product_path.starts_with(browsed_path + "/")
```

---

## Why

The two sides of the comparison sit at different levels of the tree:

- **F001 attaches products to leaf categories only.** Of 168 categories at the
  default scale, 128 are leaves and 40 are not.
- **F003.2 browses categories at every level.** A customer opens
  `Electronics` as readily as `Electronics/Computers/Laptops`.

Requiring `product.category_id == category_view.category_id` would leave those
40 categories unable to produce a single product view, and would push product
view volume below the range F003.3 specifies.

Subtree matching is also what the business means: a product listed under
`Electronics/Computers/Laptops` *is* an Electronics product, and appears when
you browse Electronics.

---

## What carries the category

A product view inherits the **browsed** `category_id` from its category view,
not the product's own leaf category. Two rules therefore apply, and both are
validated:

| Rule | Check |
| --- | --- |
| Inheritance | `product_view.category_id == category_view.category_id` |
| Containment | the product's own category is that category or below it |

The second is the one that needs path matching; the first is exact.

---

## Consequences

Category paths are the mechanism, so `categories.category_path` is
load-bearing rather than decorative. A feature that changes how paths are
built would change what containment means.

A generator drawing products for a category needs the whole subtree's pool,
not the category's own products. F003.3 precomputes one pool per category -
each product appearing in its own category's pool and in every ancestor's -
which is why a root category's pool is far larger than a leaf's.

---

## Applies to later features

Any feature that asks "is this product in this category" uses the same rule.
An order line, a return, or a category-level report must not fall back to
exact equality, or it will silently exclude every product under a
non-leaf category.
