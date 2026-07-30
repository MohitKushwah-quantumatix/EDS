# PADR-007: Configuration Ownership

**Status:** Accepted (P001.1)

## Context

Architecture review asked whether `SimulationConfig` should belong to Core or
Platform, noting that "Core should ideally contain only universally reusable
infrastructure" and "Platform should own project lifecycle".

Reviewing it exposed that the question was aimed at the wrong type.

## `SimulationConfig` stays in the domain

`SimulationConfig` aggregates thirteen retail settings models — `MasterDataConfig`,
`CheckoutConfig`, `ReviewConfig` and the rest. Moving it to Core or Platform
would drag every one of those retail types into a layer that must not know
retail exists, re-creating exactly the coupling P001 removed and breaking
PADR-002.

It is not a platform type wearing a domain's clothes; it is a domain type. It
stays in `eds/domains/retail/config.py`. **Not relocated.**

A second domain declares its own aggregate. If several domains eventually need
the same aggregate *shape*, a generic version can move to Core then — driven by
two real examples rather than one anticipated one.

## `PlatformConfig` moves Core → Platform

The type the question should have been asked about is `PlatformConfig`: seed,
timezone, locale, output directory. P001 put it in `eds.core.config`.

Those are properties of a **run**, not infrastructure. A settings model with a
`seed` field is platform policy; under PADR-004 the platform owns run
lifecycle. Core is supposed to be mechanism only.

So `PlatformConfig`, `load_platform_config` and `PLATFORM_CONFIG_FILE` move to
`eds/platform/config.py`. Core keeps only mechanism: `ConfigError`,
`DEFAULT_CONFIG_DIR`, `read_yaml_mapping`, `build_model` — none of which
expresses any policy, which is what lets every domain share them.

## Resulting split

| Module | Owns | Nature |
| --- | --- | --- |
| `eds.core.config` | `ConfigError`, `DEFAULT_CONFIG_DIR`, `read_yaml_mapping`, `build_model` | Mechanism |
| `eds.platform.config` | `PlatformConfig`, `load_platform_config` | Run policy |
| `eds.domains.retail.config` | 13 retail models, `SimulationConfig`, 13 loaders | Business policy |

`eds/config.py` re-exports all three under their original names, so no existing
import changed and no test was touched.

## Consequences

**Good.** Core is now mechanism-only, which is a defensible line to hold.
`PlatformConfig` sits beside `Project`, where the two run-settings types are
visible together.

**Cost.** `eds.domains.retail.config` now imports from `eds.platform.config`,
making domains depend on platform. That direction is correct — a domain is a
plugin of the platform — and the layering test permits it while continuing to
forbid the reverse.

## Known duplication, deliberately not resolved

`Project(name, domain, seed, output_directory)` and `PlatformConfig(seed,
timezone, locale, output_directory)` now sit in the same layer and overlap on
`seed` and `output_directory`. Two types holding the same run settings is an
inconsistency worth fixing.

It is **not** fixed here. `Project` is a placeholder with no consumers; the
right shape depends on how the clock and scheduler use it, and those do not
exist. Redesigning a placeholder before its first consumer is how placeholders
become wrong in ways that are expensive to undo.

Recommended resolution when P002 gives `Project` a consumer: `Project` holds a
`PlatformConfig` rather than repeating its fields, exposing `seed` and
`output_directory` as delegating properties so existing use keeps working.
