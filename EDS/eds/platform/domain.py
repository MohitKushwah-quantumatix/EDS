"""The domain extension point and registry.

A domain is a self-contained business simulation. The platform needs to
discover which domains exist and what each one produces, without knowing how
any of them works (PADR-002).

What the protocol deliberately does *not* carry is a ``generate()`` method.
That was tried in P001 and does not survive contact with a real domain: Retail
does not generate in one call, it generates in four ordered stages, each
reading what earlier stages wrote. A no-argument ``generate()`` could only be
implemented by duplicating the CLI's orchestration inside the domain, creating
a second execution path that nothing exercises and that would drift from the
one 1,745 tests actually cover.

So the protocol *describes* rather than *executes*. A domain declares its
stages, what each stage needs, and what each stage produces. That is exactly
the dependency graph a scheduler consumes, and it can be checked against the
real generators - which is what makes it a live abstraction rather than a
decorative one. Execution joins the protocol when there is a caller for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "DomainStage",
    "SimulationDomain",
    "available_domains",
    "get_domain",
    "list_domains",
    "register_domain",
    "resolve_domain",
]


@dataclass(frozen=True, slots=True)
class DomainStage:
    """One ordered step of a domain's generation pipeline.

    A stage is the unit a scheduler would schedule and the unit the CLI
    exposes as a command. It is described, not executed: ``requires`` and
    ``produces`` are dataset names, so the platform can compute an execution
    order without importing a single generator.

    Attributes:
        name: Stage name, matching the CLI command that runs it.
        requires: Dataset names the stage reads from earlier stages.
        produces: Dataset names the stage writes, in dependency order.
    """

    name: str
    requires: tuple[str, ...]
    produces: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject a stage that could not be scheduled or that produces nothing.

        Raises:
            ValueError: If the stage is unnamed, produces nothing, or claims to
                both require and produce the same dataset.
        """
        if not self.name.strip():
            raise ValueError("stage name must not be empty")
        if not self.produces:
            raise ValueError(f"stage {self.name!r} must produce at least one dataset")
        if overlap := set(self.requires) & set(self.produces):
            raise ValueError(f"stage {self.name!r} both requires and produces {sorted(overlap)}")


@runtime_checkable
class SimulationDomain(Protocol):
    """What the platform requires of a business domain.

    A conforming domain names itself and describes its pipeline. It never
    decides where output is written, and it is never asked to run itself by
    this protocol.
    """

    @property
    def name(self) -> str:
        """Return the domain's registry name, such as ``"retail"``."""
        ...

    @property
    def stages(self) -> tuple[DomainStage, ...]:
        """Return the domain's stages in execution order."""
        ...

    @property
    def dataset_names(self) -> tuple[str, ...]:
        """Return every dataset the domain produces, in dependency order."""
        ...


_REGISTRY: dict[str, SimulationDomain] = {}


def register_domain(domain: SimulationDomain) -> None:
    """Register a domain under its own name.

    Registration is idempotent for the same object, so a domain package that
    registers itself on import is safe to import more than once.

    Args:
        domain: The domain to register.

    Raises:
        ValueError: If the domain is unnamed, or if a *different* domain is
            already registered under that name.
    """
    if not domain.name.strip():
        raise ValueError("a domain must have a non-empty name")

    existing = _REGISTRY.get(domain.name)
    if existing is not None and existing is not domain:
        raise ValueError(f"a different domain is already registered as {domain.name!r}")
    _REGISTRY[domain.name] = domain


def list_domains() -> tuple[str, ...]:
    """Return the names of every registered domain, sorted.

    Returns:
        The registered domain names.
    """
    return tuple(sorted(_REGISTRY))


def get_domain(name: str) -> SimulationDomain:
    """Look up a registered domain by name.

    Args:
        name: Domain name, such as ``"retail"``.

    Returns:
        The registered domain.

    Raises:
        KeyError: If no domain is registered under that name.
    """
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"Unknown domain: {name!r}. Registered domains: {list_domains()}") from None


#: P001 spellings, kept so nothing that adopted them breaks. They are exact
#: aliases and are scheduled for removal at the next major version; use
#: :func:`get_domain` and :func:`list_domains`.
resolve_domain = get_domain
available_domains = list_domains
