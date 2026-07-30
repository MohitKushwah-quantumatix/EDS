# PADR-002: Platform-Independent Domains

**Status:** Accepted (P001)

## Context

Retail was not a component of the simulator; it *was* the simulator. Package
names said `generators`, `validation`, `domain` and meant retail. `config.py`
mixed `PlatformConfig` with thirteen retail settings models. Adding a second
business would have meant either renaming everything under pressure or letting
two domains share modules that were never designed for sharing.

## Decision

Retail becomes one domain package under `eds/domains/retail/`, owning its
entity schemas, generators, validation rules and configuration. A future
Healthcare, Banking or Manufacturing domain is a sibling package.

A domain owns:

* its entity schemas and enums;
* its generators;
* its business rules and validators;
* its configuration models and `configs/*.yaml` files.

A domain may depend on `eds.core`. It may not depend on another domain, and
platform code may not depend on any domain.

## Consequences

**Good.** The claim "a second domain requires no platform change" is now
checkable rather than aspirational, and the layering test checks it.

**Cost.** Two seams had to be cut.

*Configuration.* `PlatformConfig`, `ConfigError` and the YAML helpers moved to
`eds.core.config`; every retail model and loader moved to
`eds.domains.retail.config`. `DEFAULT_CONFIG_DIR` was computed from
`Path(__file__).parent.parent`, which would have silently pointed at the wrong
directory after the move; it is now anchored explicitly on the package root.

*Referential validation.* The framework defaulted to the retail master
datasets, which made `eds.core` import the retail registry. In `core` the
`declarations` argument is now required; retail restores the old default in
`eds/domains/retail/validation/referential.py`, so no caller changed.

**Accepted limitation.** `SimulationConfig` still aggregates retail sections
and is retail-owned. A second domain declares its own aggregate rather than
extending this one. Generalising it now would be guessing at requirements a
second domain has not yet stated.
