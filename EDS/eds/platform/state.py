"""Simulation state - placeholder.

**Not implemented.** Mutable simulation state, snapshots, growth and change
capture are explicitly out of scope for the platform foundation.

Today every Retail run is a pure function of ``(configuration, seed, upstream
data)`` with no state carried between runs, which is what makes the output
reproducible. Anything added here must preserve that property: state belongs
to a *project*, and a run with the same project and seed must still produce
byte-identical output.

Nothing imports this module.
"""

from __future__ import annotations

__all__: list[str] = []
