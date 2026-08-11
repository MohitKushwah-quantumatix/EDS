"""Command-line interface for eds_loader.

Commands
--------
``eds-loader run --config <file> [--dry-run]``
    Execute a loader run from a YAML config file.  ``--dry-run`` reads the
    source and previews what would be written without touching the target.

``eds-loader validate --config <file>``
    Parse the config, check that connectors are installed, and attempt a
    lightweight connectivity probe against the source.

``eds-loader init [--source <kind>] [--target <kind>] [--output <file>]``
    Generate a documented starter ``loader.yaml`` for any connector pair.

``eds-loader connectors``
    Print all registered connectors, their install status, and fix hints.

Exit codes
----------
- ``0`` — success
- ``2`` — configuration error (bad YAML, unknown connector, missing field)
- ``3`` — runtime error (I/O failure during read / write / connectivity)
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated, Optional

import typer

import eds_loader  # triggers connector self-registration  # noqa: F401
from eds_loader.cli._templates import (
    SOURCE_TEMPLATES,
    TARGET_TEMPLATES,
    build_config,
)
from eds_loader.connectors.registry import CONNECTORS, _is_package_available, get_connector
from eds_loader.config import LoaderConfig
from eds_loader.exceptions import (
    ConfigError,
    ConnectorNotFoundError,
    ConnectorNotInstalledError,
    LoadError,
)
from eds_loader.loader import load
from eds_loader.version import __version__

app = typer.Typer(
    name="eds-loader",
    help="Move EDS-generated data from any source to any target, driven by a config file.",
    add_completion=False,
    no_args_is_help=True,
)

_EXIT_OK = 0
_EXIT_CONFIG_ERROR = 2
_EXIT_LOAD_ERROR = 3

# ---------------------------------------------------------------------------
# Shared output helpers
# ---------------------------------------------------------------------------

_CHECK = "✓"
_CROSS = "✗"
_INFO  = "·"


def _ok(msg: str) -> None:
    typer.echo(f"  {_CHECK}  {msg}")


def _fail(msg: str) -> None:
    typer.echo(f"  {_CROSS}  {msg}", err=True)


def _info(msg: str) -> None:
    typer.echo(f"  {_INFO}  {msg}")


def _print_run_table(results: list) -> None:  # type: ignore[type-arg]
    """Print a plain-text table of write results with location column."""
    if not results:
        return

    # Column widths
    w_table = max(len(r.dataset) for r in results)
    w_rows  = max(len(f"{r.rows:,}") for r in results)
    w_table = max(w_table, 5)   # "Table"
    w_rows  = max(w_rows,  4)   # "Rows"

    sep   = f"+{'-' * (w_table + 2)}+{'-' * (w_rows + 2)}+{'-' * 52}+"
    hdr   = f"| {'Table':<{w_table}} | {'Rows':>{w_rows}} | {'Location':<50} |"
    typer.echo(sep)
    typer.echo(hdr)
    typer.echo(sep)
    for r in results:
        loc = r.location or ""
        if len(loc) > 50:
            loc = "…" + loc[-(49):]
        typer.echo(
            f"| {r.dataset:<{w_table}} | {r.rows:>{w_rows},} | {loc:<50} |"
        )
    typer.echo(sep)


# ---------------------------------------------------------------------------
# --version callback
# ---------------------------------------------------------------------------

def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"eds-loader {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
) -> None:
    """EDS Loader — move EDS-generated data anywhere, driven by config."""


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@app.command("run")
def run_cmd(
    config_file: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            help="Path to the loader YAML config file.",
            show_default=False,
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help=(
                "Read from source and preview what would be written "
                "without touching the target."
            ),
        ),
    ] = False,
) -> None:
    """Run the loader: read from source, write to target.

    Exits with code 2 on configuration errors, 3 on load failures.
    Use ``--dry-run`` to preview the load without writing any data.
    """
    try:
        config = LoaderConfig.from_yaml(config_file)
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)

    # ── Dry-run branch ────────────────────────────────────
    if dry_run:
        typer.echo("\nDRY RUN — no data will be written.\n")
        try:
            source = get_connector(config.source.kind, config.source.extra_fields())
            if config.schema_required:
                schema_meta = source.read_schema_metadata()
                names = list(config.tables) if config.tables else list(schema_meta)
            else:
                # No schema.json — auto-discover by listing parquet files
                names = list(config.tables) if config.tables else None
            datasets = source.read_datasets(names=names)
        except (ConnectorNotFoundError, ConnectorNotInstalledError, ConfigError) as exc:
            typer.echo(f"Configuration error: {exc}", err=True)
            raise typer.Exit(code=_EXIT_CONFIG_ERROR)
        except LoadError as exc:
            typer.echo(f"Read failed: {exc}", err=True)
            raise typer.Exit(code=_EXIT_LOAD_ERROR)

        if not datasets:
            typer.echo("  No datasets found in source.")
            raise typer.Exit(code=_EXIT_OK)

        w = max(len(n) for n in datasets)
        total = 0
        for name, df in datasets.items():
            typer.echo(f"  {name:<{w}}  {df.width} cols, {df.height:,} rows")
            total += df.height
        typer.echo(f"\nTotal: {total:,} rows across {len(datasets)} dataset(s).")
        typer.echo("Run without --dry-run to write.")
        return

    # ── Live run ──────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        result = load(config)
    except (ConnectorNotFoundError, ConnectorNotInstalledError, ConfigError) as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)
    except LoadError as exc:
        typer.echo(f"Load failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_LOAD_ERROR)

    elapsed = time.monotonic() - t0

    _print_run_table(result.write_results)
    typer.echo(
        f"\nDone — {result.total_rows:,} rows across "
        f"{len(result.tables_written)} table(s) in {elapsed:.1f} s."
    )


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

@app.command("validate")
def validate_cmd(
    config_file: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            help="Path to the loader YAML config file.",
            show_default=False,
        ),
    ],
) -> None:
    """Validate a config file: parse, check connectors, probe source.

    Exits with code 2 on configuration errors, 3 on connectivity errors.
    """
    typer.echo()

    # Step 1 — parse YAML → LoaderConfig
    try:
        config = LoaderConfig.from_yaml(config_file)
        _ok(f"Config parsed:  {config_file}")
    except ConfigError as exc:
        _fail(f"Config parse error: {exc}")
        typer.echo(
            "\nFix the errors above, then re-run:\n"
            f"  eds-loader validate -c {config_file}\n",
            err=True,
        )
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)

    # Step 2 — check source connector is installed
    source_kind = config.source.kind
    source_spec = CONNECTORS.get(source_kind)
    if source_spec is None:
        _fail(f"Unknown source kind: {source_kind!r}")
        typer.echo(
            f"\nRun 'eds-loader connectors' to see registered kinds.\n", err=True
        )
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)
    missing_src = [p for p in source_spec.required_packages
                   if not _is_package_available(p)]
    if missing_src:
        _fail(
            f"Source connector {source_kind!r} requires: {', '.join(missing_src)}\n"
            f"       Fix: pip install eds-loader[{source_spec.install_extra}]"
        )
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)
    _ok(f"Source connector: {source_kind}  (installed)")

    # Step 3 — check target connector is installed
    target_kind = config.target.kind
    target_spec = CONNECTORS.get(target_kind)
    if target_spec is None:
        _fail(f"Unknown target kind: {target_kind!r}")
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)
    missing_tgt = [p for p in target_spec.required_packages
                   if not _is_package_available(p)]
    if missing_tgt:
        _fail(
            f"Target connector {target_kind!r} requires: {', '.join(missing_tgt)}\n"
            f"       Fix: pip install eds-loader[{target_spec.install_extra}]"
        )
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)
    _ok(f"Target connector: {target_kind}  (installed)")

    # Step 4 — probe source: read schema.json (skipped if schema_required=False)
    if not config.schema_required:
        _ok("Schema check skipped  (schema_required: false)")
        typer.echo("\nConfig is valid — schema.json will not be read; datasets will be\n"
                   "auto-discovered from *.parquet files at the source.\n")
        return

    try:
        source = get_connector(source_kind, config.source.extra_fields())
        schema_meta = source.read_schema_metadata()
        dataset_names = list(schema_meta)
        n = len(dataset_names)
        preview = ", ".join(dataset_names[:4])
        if n > 4:
            preview += f", … (+{n - 4} more)"
        _ok(f"Schema found: {n} dataset(s)  ({preview})")
    except (ConnectorNotFoundError, ConnectorNotInstalledError, ConfigError) as exc:
        _fail(f"Connector error: {exc}")
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)
    except LoadError as exc:
        _fail(f"Source connectivity error: {exc}")
        typer.echo(
            "\nCheck your source credentials and network access.\n", err=True
        )
        raise typer.Exit(code=_EXIT_LOAD_ERROR)

    typer.echo(f"\nConfig is valid — {n} dataset(s) ready to load.\n")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@app.command("init")
def init_cmd(
    source: Annotated[
        str,
        typer.Option(
            "--source",
            "-s",
            help=(
                "Source connector kind. "
                f"Choices: {', '.join(sorted(SOURCE_TEMPLATES))}."
            ),
        ),
    ] = "local_fs",
    target: Annotated[
        str,
        typer.Option(
            "--target",
            "-t",
            help=(
                "Target connector kind. "
                f"Choices: {', '.join(sorted(TARGET_TEMPLATES))}."
            ),
        ),
    ] = "postgres",
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            help="Path for the generated config file.",
        ),
    ] = Path("loader.yaml"),
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Overwrite the output file if it already exists.",
        ),
    ] = False,
) -> None:
    """Generate a documented starter loader.yaml for any connector pair.

    Exits with code 2 if the kind is unknown or the file already exists
    without --force.
    """
    # Validate kinds
    if source not in SOURCE_TEMPLATES:
        typer.echo(
            f"Unknown source kind: {source!r}\n"
            f"Known source kinds: {', '.join(sorted(SOURCE_TEMPLATES))}",
            err=True,
        )
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)
    if target not in TARGET_TEMPLATES:
        typer.echo(
            f"Unknown target kind: {target!r}\n"
            f"Known target kinds: {', '.join(sorted(TARGET_TEMPLATES))}",
            err=True,
        )
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)

    # Guard against overwrite
    if output.exists() and not force:
        typer.echo(
            f"File already exists: {output}\n"
            "Use --force to overwrite.",
            err=True,
        )
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)

    content = build_config(source, target)
    output.write_text(content, encoding="utf-8")

    typer.echo(f"\nGenerated {output}  (source={source}, target={target})\n")
    typer.echo("Fill in the required fields, then validate:\n")
    typer.echo(f"  eds-loader validate -c {output}")
    typer.echo(f"  eds-loader run      -c {output}\n")


# ---------------------------------------------------------------------------
# connectors
# ---------------------------------------------------------------------------

@app.command("connectors")
def connectors_cmd() -> None:
    """Show all known connectors, install status, and how to install missing ones."""
    if not CONNECTORS:
        typer.echo("No connectors are registered yet.")
        return

    _DB_KINDS      = {"postgres", "mysql", "mssql", "oracle", "mongodb"}
    _STORAGE_KINDS = {"local_fs", "remote_fs", "s3", "azure_blob", "gcs"}

    registered       = set(CONNECTORS)
    db_registered    = sorted(registered & _DB_KINDS)
    storage_registered = sorted(registered & _STORAGE_KINDS)
    other_registered = sorted(registered - _DB_KINDS - _STORAGE_KINDS)

    any_missing = False

    def _print_connector(kind: str) -> None:
        nonlocal any_missing
        spec = CONNECTORS[kind]
        missing  = [p for p in spec.required_packages if not _is_package_available(p)]
        installed = not missing and spec.connector_class is not None
        status = "[OK]" if installed else "[--]"
        caps   = "/".join(
            filter(None, [
                "source" if spec.can_read  else "",
                "target" if spec.can_write else "",
            ])
        )
        hint = (
            f"  ->  pip install eds-loader[{spec.install_extra}]"
            if not installed else ""
        )
        typer.echo(f"  {status} {kind:<14} ({caps:<13}){hint}")
        if not installed:
            any_missing = True

    if db_registered:
        typer.echo("DATABASE")
        for kind in db_registered:
            _print_connector(kind)

    if storage_registered:
        typer.echo("\nSTORAGE")
        for kind in storage_registered:
            _print_connector(kind)

    if other_registered:
        typer.echo("\nOTHER")
        for kind in other_registered:
            _print_connector(kind)

    if any_missing:
        typer.echo("\nInstall everything at once:  pip install eds-loader[all]")
