# ADR-008 - Golden Record Principle

**Status:** Accepted

**Applies from:** F006

---

## Decision

Every transactional entity originates from exactly one parent entity. Each
entity owns exactly one parent, and downstream entities are never generated
independently.

### Ownership

The parent an entity belongs to:

```
Customer
  └── Session
        ├── Category View
        │     ├── Search
        │     └── Product View
        └── Shopping Cart
              └── Cart Item
                    └── Checkout ... Order ... Payment ... Shipment
                                                            └── Return
                                                                  └── Review
```

A **shopping cart's parent is the session**, not a wishlist. A cart is opened
during a browsing session; it is not created out of a wishlist.

### Origination

A **cart item originates from a product view**. That is where the customer saw
the product, and it is the reference every cart item carries.

A **wishlist is optional enrichment**. It influences a cart item - the
customer may add a product from their saved list rather than straight from the
page - but it is neither the parent of a cart item nor of a cart. When a cart
item comes from a wishlist it still carries the product view the wishlist
entry was saved from, so the line back to a real page view is never broken.

```
Session -> Shopping Cart -> Cart Item -> Product View
                                 ^
                                 └── Wishlist (optional enrichment)
```

---

## Consequences

A generator receives its parent rows and walks them. It never samples the
customer or product pools directly to decide what exists.

"Exactly one parent" governs **lineage**, not the number of foreign keys. A
row may carry additional references for convenience - a denormalised
`customer_id`, a geography key - provided they are copied from the parent
rather than chosen independently. The test for a denormalised key is that it
must agree with the parent; every feature from F003.2 onward asserts exactly
that.

---

## Current state

Audited against the shipped schemas. The lineage parent of each transactional
entity:

| Entity | Lineage parent | Denormalised references |
| --- | --- | --- |
| `sessions` | `customers` | geography |
| `category_views` | `sessions` | `customer_id`, `category_id` |
| `search_history` | `category_views` | `session_id`, `customer_id`, `category_id` |
| `product_views` | `category_views` | `session_id`, `customer_id`, `category_id`, `product_id`, optional `search_id` |
| `wishlists` | `product_views` | `customer_id`, `product_id` |
| `shopping_carts` | `sessions` | `customer_id` |
| `cart_items` | `shopping_carts` | `customer_id`, `product_id`, `product_view_id`, optional `wishlist_id` |
| `checkout` | `shopping_carts` | `customer_id`, `session_id`, two address keys |

Every denormalised key above is copied from the parent and asserted to agree
with it by a test.

---

## Clarification history

An earlier draft of this ADR presented the lineage as a single flat chain
that read `Wishlist -> Shopping Cart`. That was not the intended lineage and
does not match the implementation: `shopping_carts` carries no `wishlist_id`
and never has.

The wording above replaces it. A later feature must not add a `wishlist_id`
to `shopping_carts` expecting one to belong there - the wishlist reference
lives on `cart_items`, where it is nullable and populated only when the item
came from the saved list.
