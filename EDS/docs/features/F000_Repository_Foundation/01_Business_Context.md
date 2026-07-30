# F000 - Repository Foundation

| Field | Value |
| --- | --- |
| Feature ID | F000 |
| Title | Repository Foundation |
| Status | Complete |
| Depends on | - |

## Purpose

Establish the repository skeleton, packaging, and tooling that every
subsequent feature builds on. This feature delivers no business behaviour.

## Scope

In scope:

- Repository structure and Python package layout
- `pyproject.toml`, `pytest.ini`, `ruff.toml`
- `README.md` and MIT `LICENSE`
- Platform configuration files under `configs/`
- Package initialisation and the public version module
- A minimal Typer CLI exposing `eds --help`
- Placeholder files required for package integrity

Explicitly out of scope:

- Business entities and domain models
- Event classes, workflows, and simulation logic
- Exporters, validators, and business rules

## Requirements

1. Python 3.12 or newer.
2. Approved dependencies only: Polars, Pydantic, Faker, Typer, PyYAML;
   PyTest, Ruff, and mypy for development.
3. Comprehensive type hints throughout.
4. Module-level docstrings on every module.
5. `configs/` contains platform defaults only - no business configuration.
6. The version is public API, imported as `from eds.version import __version__`.

## Acceptance criteria

All four commands must succeed:

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy eds
```

`eds --help` must exit 0 and describe the application.

## Notes

- `eds/version.py` is the single source of truth for the version; the build
  backend reads it, so distribution and runtime versions cannot drift.
- The directory tree is created as importable packages. The business modules
  named in the architecture sketch (`events/customer_events.py`,
  `simulation/scheduler.py`, and so on) are deliberately absent until the
  features that own them.
