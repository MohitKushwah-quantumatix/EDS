"""Public version API for the Enterprise Data Simulator.

``eds.version`` is part of the package's public surface; callers import the
version from here::

    from eds.version import __version__

The build backend also reads ``__version__`` from this module (see the
``[tool.hatch.version]`` table in ``pyproject.toml``), so the distribution
version and the runtime version can never drift apart.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__: str = "0.1.0"
