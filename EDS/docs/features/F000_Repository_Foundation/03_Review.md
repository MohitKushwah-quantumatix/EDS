# F000 - Review

| Field | Value |
| --- | --- |
| Outcome | Accepted with change requests, all applied |
| Environment | Windows 10, Python 3.13.0 |
| Verified | `pip install -e ".[dev]"`, `pytest`, `ruff check .`, `mypy eds` |

## Verification

| Gate | Result |
| --- | --- |
| `pip install -e ".[dev]"` | Pass - builds `eds-0.1.0` |
| `pytest` | Pass - 87 passed |
| `ruff check .` | Pass - all checks passed |
| `ruff format --check .` | Pass - 37 files formatted |
| `mypy eds` | Pass - no issues in 34 source files |
| `eds --help` | Exit 0, describes the application |
| `eds version` | Prints `0.1.0` |

## Test coverage

| Area | Tests |
| --- | --- |
| Package layout | 63 - every package importable and documented, `py.typed` present, required root files present, undeclared subpackage raises |
| Platform configs | 13 - both files parse, exact platform key sets, typed defaults, no business keys, missing file and malformed YAML raise |
| CLI | 6 - help, version output, no-args help; unknown command and unknown option exit non-zero |
| Version | 5 - type, semver shape, re-export identity, distribution metadata agreement, no stray exports |
| **Total** | **87** |

## Change requests raised

### CR1 - Version module is public API

`eds/_version.py` implied an internal implementation detail. The architecture
references `from eds.version import __version__`.

**Resolution:** moved to `eds/version.py`. Updated the three import sites
(`eds/__init__.py`, `eds/cli/main.py`, `eds/tests/test_cli.py`), the test that
introspects the module, and the `[tool.hatch.version]` path. No compatibility
shim was left behind, since no released version referenced the old path.

### CR2 - Create the configuration files

The original implementation left `configs/` empty because the key set was
unclear. Clarified: `configs/` holds *platform* configuration, not business
configuration.

**Resolution:** added `configs/simulation.yaml` (seed, timezone, locale,
output_directory) and `configs/logging.yaml` (log_level, log_format,
date_format, log_to_console, log_file). A test asserts each file's key set
exactly, so business configuration cannot drift in unnoticed.

### CR3 - Per-feature documentation folders

Flat feature documentation does not scale past ~50 features.

**Resolution:** adopted `docs/04_Features/F<NNN>/` containing `Feature.md`,
`ClaudePrompt.md`, and `Review.md`. F000 is the first folder and sets the
pattern.

## Defects found and fixed during verification

1. **Build failure.** Hatchling's default version regex does not accept the
   `__version__: str` annotation required by the type-hint rule. Fixed with an
   explicit `pattern` in `[tool.hatch.version]` rather than dropping the hint.
2. **Lint failures.** 25 generated package docstrings tripped D209 (closing
   quotes on the content line); auto-fixed. The CR1 rename left the imports in
   `test_cli.py` un-sorted (I001); auto-fixed.

## Notes for later features

- `A005` is globally ignored in `ruff.toml` because the specified structure
  mandates `eds/exporters/csv/`, which shadows the standard library module
  name. If that package is ever renamed, drop the ignore.
- No configuration *loader* exists yet. The YAML files are data only; the
  feature that introduces the loader should validate them with Pydantic and
  own the precedence rules between file, environment, and CLI flags.
- `configs/` is included in the sdist but not in the wheel. The config tests
  resolve paths relative to the repository root and therefore assume a
  source checkout.
