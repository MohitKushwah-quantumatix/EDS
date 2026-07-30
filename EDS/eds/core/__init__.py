"""Domain-independent infrastructure shared by every simulation domain.

This is the bottom of the dependency graph. Nothing here knows about retail,
healthcare or any other business domain, and nothing here may import from
:mod:`eds.domains` or :mod:`eds.adapters` (PADR-001, PADR-002).

Contents: the declarative dataset schema, deterministic random streams, frame
construction helpers, the validation framework, and configuration loading.
"""
