# F003.3 - Claude Prompt

## Role

Senior Python Engineer working on the Enterprise Data Simulator.

Constraints given:

- Implement F003.3 exactly as described.
- Do not redesign existing architecture.
- Do not refactor previous features.
- Do not implement future features.
- Follow the conventions established in F000, F001, F002, F003.1 and F003.2.
- Stop after F003.3 is complete.

## Task

Simulate product browsing and wishlist behaviour for existing category views,
producing `product_views.parquet` and `wishlists.parquet`.

Read the F001, F002, F003.1 and F003.2 datasets; never regenerate them.

## Module structure

```
eds/generators/journey/
    product_view_generator.py
    wishlist_generator.py
    engagement.py
eds/validation/engagement_validation.py
```

## CLI

Extend `eds generate journey`. Do not introduce a new CLI command.

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

Stop after implementing the two datasets. Do not implement shopping cart,
checkout, orders, payments, returns, or reviews. Do not begin F004.

## Points resolved without escalation

1. **"The product must belong to the same category as the category_view"
   cannot mean exact equality.** F001 attaches products to leaf categories
   only, while F003.2 browses categories at every level, so 40 of 168
   categories have no products of their own. Read as subtree containment: a
   view of `Electronics` draws from every product beneath it.
2. **Product views cannot nest inside a category view's window.** A category
   view lasts up to 180 seconds, but three product views averaging 45 seconds
   need more than that. Placed in session time instead, which is what the
   stated data-quality rule ("no timestamp outside the session") requires.
3. **The naive popularity weights under-deliver.** The view-share over
   catalog-share ratio only reaches 70/20/10 when every pool mirrors the
   catalog; leaf pools hold about eight products and roughly one in six has no
   popular product at all. Weights were calibrated against the achieved
   distribution.
4. **A single per-view wishlist probability cannot produce the documented
   outcome.** At ~85 views per customer, any rate that fills a wishlist gives
   almost every customer one. Modelled as adoption then adding.
