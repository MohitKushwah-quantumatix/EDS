# F004 - Claude Prompt

## Role

Senior Python Engineer working on the Enterprise Data Simulator.

Constraints given:

- Implement F004 exactly as described.
- Do not redesign the existing architecture.
- Do not refactor previous features.
- Do not modify schemas from previous features.
- Do not implement future features.
- Follow the conventions established in F000 through F003.3.
- Stop after F004 is complete.

## Task

Convert browsing behaviour into purchase intent, producing
`shopping_carts.parquet` and `cart_items.parquet`.

Read the F001, F002, F003.1 and F003.3 datasets; never regenerate them.

## Module structure

```
eds/generators/commerce/
    cart_generator.py
    cart_item_generator.py
    commerce.py
eds/validation/commerce_validation.py
configs/commerce.yaml
```

## CLI

`eds generate commerce`. Do not introduce additional CLI commands.

## Required report

1. Files created.
2. Files modified.
3. Commands executed.
4. Test results.
5. Design decisions.
6. Assumptions.
7. Known limitations.
8. Suggested improvements.

## Stop condition

Stop after implementing the two datasets. Do not implement checkout, orders,
payments, shipments, returns, or reviews. Do not begin F005.

## Points resolved without escalation

1. **A cart's own columns depend on the items it receives.** `item_count`,
   `created_at` and `updated_at` cannot be generated before the items exist,
   so cart creation is split into planning and building.
2. **A wishlist entry can predate the session the cart is opened in.** That is
   the whole point of the wishlist flow, but it means the add time cannot
   simply be "wishlist time plus a delay" - the add happens during the cart's
   own session.
3. **`configs/commerce.yaml` was placed at the repository root**, not under
   `eds/`, matching where every earlier feature's configuration lives.
4. **A cart item still needs `product_view_id` when added from a wishlist.**
   A wishlist entry records the view it was saved from, so the chain back to a
   real page view is preserved rather than broken.
