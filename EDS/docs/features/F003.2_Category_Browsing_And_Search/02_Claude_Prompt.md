# F003.2 - Claude Prompt

## Role

Senior Python Engineer working on the Enterprise Data Simulator.

Constraints given:

- Implement F003.2 exactly as described.
- Do not redesign existing architecture.
- Do not refactor previous features.
- Do not implement future features.
- Follow the conventions established in F000, F001, F002 and F003.1.
- Stop after F003.2 is complete.

## Task

Simulate category browsing and searches for every existing session, producing
`category_views.parquet` and `search_history.parquet`.

Read the F001, F002 and F003.1 datasets; never regenerate them.

## Module structure

```
eds/generators/journey/
    category_generator.py
    search_generator.py
    browsing.py
eds/validation/browsing_validation.py
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

Stop after implementing the two datasets. Do not implement product views,
wishlists, shopping carts, orders, or payments. Do not begin F003.3.

## Points resolved without escalation

1. **The specification names five search vocabularies; F001 has fourteen
   top-level categories.** Two of the five use different names in F001
   ("Fashion" is `Clothing`, "Sports" is `Sports & Outdoors`). The five were
   implemented verbatim under their F001 names and vocabularies added for the
   remaining nine, so every browsable section can produce a relevant search.
2. **`products.parquet` is listed as a dependency but no output field
   references a product.** Consistent with F003.1, it is not read.
3. **An early `pages_viewed` ceiling put category-view volume below the stated
   28,000–32,000 range.** It was removed; the specification's per-persona view
   ranges take precedence over a constraint it never asked for.
