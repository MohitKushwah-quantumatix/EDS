"""Command-line interface for eds_loader.

Two commands are provided:

``eds-loader run --config <file>``
    Execute a loader run from a YAML config file.  Reads datasets from the
    configured source and writes them to the configured target.

``eds-loader connectors``
    Print a table of every registered connector, whether its Python driver is
    installed, and the exact ``pip install`` command to fix any that are
    missing.

Exit codes
----------
- ``0`` — success
- ``2`` — configuration error (bad config file, unknown connector kind, etc.)
- ``3`` — load failure (I/O error during read/write)
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from eds_loader.connectors.registry import CONNECTORS, _is_package_available
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


@app.command("run")
def run(
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
    """Run the loader: read from source, write to target.

    Exits with code 2 on configuration errors, 3 on load failures.
    """
    try:
        config = LoaderConfig.from_yaml(config_file)
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)

    try:
        result = load(config)
    except (ConnectorNotFoundError, ConnectorNotInstalledError, ConfigError) as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)
    except LoadError as exc:
        typer.echo(f"Load failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_LOAD_ERROR)

    # Success summary
    typer.echo(
        f"Done. {result.total_rows:,} rows written across "
        f"{len(result.tables_written)} table(s)."
    )
    if result.tables_written:
        width = max(len(t) for t in result.tables_written)
        for table in result.tables_written:
            typer.echo(f"  {table:<{width}}  {result.rows_written[table]:>12,} rows")


@app.command("connectors")
def connectors_cmd() -> None:
    """Show all known connectors, install status, and how to install missing ones."""
    if not CONNECTORS:
        typer.echo("No connectors are registered yet.")
        typer.echo(
            "\nConnectors are added in Steps 3–9 of the build order.\n"
            "See the requirements document, Section 9."
        )
        return

    # Connector families for display grouping
    _DB_KINDS = {"postgres", "mysql", "mssql", "oracle", "mongodb"}
    _STORAGE_KINDS = {"local_fs", "remote_fs", "s3", "azure_blob", "gcs"}

    registered = set(CONNECTORS)
    db_registered = sorted(registered & _DB_KINDS)
    storage_registered = sorted(registered & _STORAGE_KINDS)
    other_registered = sorted(registered - _DB_KINDS - _STORAGE_KINDS)

    any_missing = False

    def _print_connector(kind: str) -> None:
        nonlocal any_missing
        spec = CONNECTORS[kind]
        missing = [p for p in spec.required_packages if not _is_package_available(p)]
        installed = not missing and spec.connector_class is not None

        status = "[OK]" if installed else "[--]"
        caps = "/".join(
            filter(None, ["source" if spec.can_read else "", "target" if spec.can_write else ""])
        )
        hint = f"  ->  pip install eds-loader[{spec.install_extra}]" if not installed else ""
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
