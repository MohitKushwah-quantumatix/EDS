"""Enterprise Data Simulator (EDS).

EDS generates synthetic enterprise datasets by simulating business events.
Business events drive state changes, state changes produce data, and the
resulting records preserve referential integrity and chronological order.

This module exposes only the package version. Domain models, events,
workflows, simulation logic, exporters, and validators are introduced by
subsequent features.
"""

from __future__ import annotations

from eds.version import __version__

__all__ = ["__version__"]
