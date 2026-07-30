# F000 - Claude Prompt

## Role

Senior Python Software Engineer implementing features for the Enterprise Data
Simulator (EDS).

Constraints given:

- Do not redesign the architecture.
- Do not invent new abstractions.
- Follow the provided Feature Specification exactly.
- If the specification is ambiguous, stop and report the ambiguity rather than
  making architectural decisions.

## Technology

Python 3.12+, Polars, Pydantic, Faker, Typer, PyYAML, PyTest.

## Architecture principles

- Business events drive state changes.
- State changes produce data.
- Maintain referential integrity.
- Preserve chronological consistency.
- Keep the implementation simple and readable.
- Avoid premature abstraction.
- Prefer composition over inheritance.
- Write deterministic code when a random seed is provided.

## Task

Implement only the repository foundation:

- Repository structure
- Python package layout
- `pyproject.toml`
- `pytest.ini`
- `ruff.toml`
- `README.md`
- `LICENSE` (MIT)
- Configuration files
- Package initialisation
- Version module
- Minimal Typer CLI (`eds --help`)
- Placeholder files required for package integrity

Do not create business entities, event classes, workflows, simulation logic,
exporters, validators, or business rules.

Requirements: Python 3.12+, approved dependencies only, comprehensive type
hints, module-level docstrings, and `pip install -e .`, `pytest`,
`ruff check .`, and `mypy eds` must all succeed.

## Required report

1. Files created.
2. Files modified.
3. Commands executed.
4. Test results.
5. Any assumptions made.

## Follow-up change requests

1. Move `eds/_version.py` to `eds/version.py` - it is public API, not an
   internal implementation detail, and the architecture references
   `from eds.version import __version__`.
2. Create `configs/simulation.yaml` and `configs/logging.yaml` with platform
   defaults only (seed, timezone, locale, output directory, log level).
   Nothing business-specific.
3. Reorganise documentation so each feature owns a folder
   (`04_Features/F000/`) containing `Feature.md`, `ClaudePrompt.md`, and
   `Review.md`, for navigability at 50+ features.
