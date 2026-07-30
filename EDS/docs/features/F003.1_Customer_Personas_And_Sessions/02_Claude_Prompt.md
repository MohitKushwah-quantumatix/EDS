# F003.1 - Claude Prompt

## Role

Senior Python Engineer working on the Enterprise Data Simulator.

Constraints given:

- Implement F003.1 exactly as described.
- Do not redesign previous features.
- Do not implement future features.
- Follow all repository conventions established in F000, F001 and F002.
- Stop after F003.1 is complete.

## Task

Generate realistic customer personas and browsing sessions, producing
`customer_personas.parquet` and `sessions.parquet`.

Read the F001 and F002 datasets; never regenerate them.

## Module structure

```
eds/generators/journey/
    persona_generator.py
    session_generator.py
    journey.py
eds/domain/journey/
    schema.py
    enums.py
eds/validation/journey_validation.py
```

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

Stop after implementing the two datasets. Do not implement searches, product
views, or wishlists. Do not start F003.2.

## Points resolved without escalation

The specification is concrete enough to implement directly. Three points
needed a judgement call, resolved in line with the stated principles and
recorded in `03_Review.md`:

1. **`products.parquet` and `categories.parquet` are listed as dependencies
   but no output field references them.** Product views are explicitly out of
   scope, so requiring them would create a false coupling. They are not read.
2. **Session counts drawn straight from the persona ranges overshoot the
   stated expected output.** Scaling by customer tenure both fixes the volume
   and is the more realistic model.
3. **"Sessions within the last five years" needs an anchor.** The reference
   date is taken from `customers.yaml` rather than duplicated, so the session
   window can never disagree with the registration window.
