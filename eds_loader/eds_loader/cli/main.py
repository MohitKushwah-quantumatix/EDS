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

import logging
import time
from pathlib import Path
from typing import Annotated

import typer

import eds_loader  # triggers connector self-registration  # noqa: F401
from eds_loader._logging import configure_logging, get_logger
from eds_loader._progress import TerminalProgress
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

logger = get_logger(__name__)

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


def _print_incremental_table(result: Any, elapsed: float) -> None:
    """Print a human-friendly incremental run summary table."""
    from eds_loader.loader import LoadResult  # avoid circular at module level

    all_names: list[str] = list(result.tables_written) + list(result.tables_skipped)
    if not all_names:
        typer.echo("\n  No datasets found.\n")
        return

    w = max(len(n) for n in all_names)
    w = max(w, 7)  # "Dataset"

    typer.echo(f"\n  {'Dataset':<{w}}  {'Status':<8}  {'Inserted':>10}  {'Updated':>10}  {'Location'}")
    typer.echo(f"  {'-' * w}  {'-' * 8}  {'-' * 10}  {'-' * 10}  {'-' * 40}")

    for r in result.write_results:
        loc = r.location or ""
        if len(loc) > 40:
            loc = "…" + loc[-39:]
        typer.echo(
            f"  {r.dataset:<{w}}  {'CHANGED':<8}  "
            f"{r.rows_inserted:>10,}  {r.rows_updated:>10,}  {loc}"
        )

    for name in result.tables_skipped:
        typer.echo(f"  {name:<{w}}  {'SKIPPED':<8}  {'—':>10}  {'—':>10}  (no changes detected)")

    changed = len(result.tables_written)
    skipped = len(result.tables_skipped)
    affected = result.total_rows
    typer.echo(
        f"\nDone — {affected:,} row(s) affected "
        f"({changed} changed, {skipped} skipped) in {elapsed:.1f} s."
    )


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
    """EDS Loader — move EDS-generated data anywhere, driven by config.

    Every run is automatically logged to ``logs/<date>.log`` — no flags
    needed. The console shows a live progress bar instead of raw log text.
    """
    configure_logging()


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
    logger.info("eds-loader run invoked (config=%s, dry_run=%s)", config_file, dry_run)
    try:
        config = LoaderConfig.from_yaml(config_file)
    except ConfigError as exc:
        logger.error("Config parse failed: %s", exc)
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)

    logger.info(
        "Config loaded: source=%s target=%s tables=%s enforce_constraints=%s "
        "schema_required=%s",
        config.source.kind, config.target.kind,
        list(config.tables) or "(all)",
        config.enforce_constraints, config.schema_required,
    )

    # ── Dry-run branch ────────────────────────────────────
    if dry_run:
        typer.echo("\nDRY RUN — no data will be written.\n")
        progress = TerminalProgress()
        eds_root_logger = logging.getLogger("eds_loader")
        eds_root_logger.addHandler(progress)
        try:
            source = get_connector(config.source.kind, config.source.extra_fields())
            if config.schema_required:
                schema_meta = source.read_schema_metadata()
                names = list(config.tables) if config.tables else list(schema_meta)
            else:
                # No schema.json — auto-discover by listing parquet files
                names = list(config.tables) if config.tables else None
            logger.info("Dry-run: reading %s dataset(s) from source", names or "(auto-discovered)")
            datasets = source.read_datasets(names=names)
        except (ConnectorNotFoundError, ConnectorNotInstalledError, ConfigError) as exc:
            logger.error("Dry-run configuration error: %s", exc)
            typer.echo(f"Configuration error: {exc}", err=True)
            raise typer.Exit(code=_EXIT_CONFIG_ERROR)
        except LoadError as exc:
            logger.error("Dry-run read failed: %s", exc)
            typer.echo(f"Read failed: {exc}", err=True)
            raise typer.Exit(code=_EXIT_LOAD_ERROR)
        finally:
            eds_root_logger.removeHandler(progress)
            progress.close()

        if not datasets:
            logger.warning("Dry-run: no datasets found in source")
            typer.echo("  No datasets found in source.")
            raise typer.Exit(code=_EXIT_OK)

        w = max(len(n) for n in datasets)
        total = 0
        for name, df in datasets.items():
            typer.echo(f"  {name:<{w}}  {df.width} cols, {df.height:,} rows")
            total += df.height
        logger.info("Dry-run complete: %d row(s) across %d dataset(s)", total, len(datasets))
        typer.echo(f"\nTotal: {total:,} rows across {len(datasets)} dataset(s).")
        typer.echo("Run without --dry-run to write.")
        return

    # ── Live run ──────────────────────────────────────────────────────
    t0 = time.monotonic()
    progress = TerminalProgress()
    eds_root_logger = logging.getLogger("eds_loader")
    eds_root_logger.addHandler(progress)
    try:
        result = load(config, config_path=config_file)
    except (ConnectorNotFoundError, ConnectorNotInstalledError, ConfigError) as exc:
        logger.error("Configuration error: %s", exc)
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)
    except LoadError as exc:
        logger.error("Load failed after %.1fs: %s", time.monotonic() - t0, exc)
        typer.echo(f"Load failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_LOAD_ERROR)
    finally:
        eds_root_logger.removeHandler(progress)
        progress.close()

    elapsed = time.monotonic() - t0
    logger.info(
        "Run complete: %d row(s) across %d table(s) in %.1fs",
        result.total_rows, len(result.tables_written), elapsed,
    )

    if result.load_mode == "incremental":
        _print_incremental_table(result, elapsed)
    else:
        _print_run_table(result.write_results)
        typer.echo(
            f"\nDone — {result.total_rows:,} rows across "
            f"{len(result.tables_written)} table(s) in {elapsed:.1f} s."
        )



# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@app.command("status")
def status_cmd(
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
    """Show the config, connectivity, and last-run state for a loader config."""
    try:
        config = LoaderConfig.from_yaml(config_file)
    except ConfigError as exc:
        typer.echo(f"  {_CROSS}  Config error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)

    typer.echo(f"\nConfig:  {config_file}\n")
    typer.echo(f"  Source:       {config.source.kind}")
    typer.echo(f"  Target:       {config.target.kind}")
    typer.echo(f"  Load mode:    {config.load_mode}")
    typer.echo(f"  Parallelism:  {config.parallelism}")
    typer.echo(f"  Batch size:   {config.batch_size or '(unlimited)'}")
    typer.echo(f"  Validation:   on_error={config.on_validation_error}")
    typer.echo(f"  Schema drift: {config.schema_drift}")
    if config.load_mode == "incremental":
        typer.echo(f"  Delete mode:  {config.delete_mode}")

    # Source connectivity probe
    typer.echo("")
    try:
        source = get_connector(config.source.kind, config.source.extra_fields())
        if config.schema_required:
            schema_meta = source.read_schema_metadata()
            n = len(schema_meta)
            names_preview = ", ".join(list(schema_meta)[:4])
            if n > 4:
                names_preview += f" … (+{n - 4})"
            _ok(f"Source reachable — {n} dataset(s): {names_preview}")
        else:
            _ok("Source reachable (schema_required=false)")
    except (ConnectorNotFoundError, ConnectorNotInstalledError) as exc:
        _fail(f"Source connector error: {exc}")
    except Exception as exc:
        _fail(f"Source connectivity error: {exc}")

    # State file
    from eds_loader._state import load_state
    from eds_loader.loader import _resolve_state_path
    state_path = _resolve_state_path(config, config_file)
    typer.echo(f"\n  State file:   {state_path}")
    state = load_state(state_path)
    if state:
        _ok(f"State loaded — last run: {state.last_run}")
        typer.echo("")
        typer.echo(f"  {'Dataset':<22}  {'Last Changed':<26}  {'Rows':<10}  {'Status'}")
        typer.echo("  " + "─" * 75)
        for name, ds in state.datasets.items():
            status_txt = "SKIPPED" if ds.skipped else "CHANGED"
            typer.echo(
                f"  {name:<22}  {ds.last_changed:<26}  "
                f"{ds.rows_at_source:<10,}  {status_txt}"
            )
    else:
        _info("No state file found — next run will be a full load")

    typer.echo("")


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

@app.command("reset")
def reset_cmd(
    config_file: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            help="Path to the loader YAML config file.",
            show_default=False,
        ),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Delete the incremental state file to force a full reload on the next run."""
    try:
        config = LoaderConfig.from_yaml(config_file)
    except ConfigError as exc:
        typer.echo(f"Config error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)

    from eds_loader.loader import _resolve_state_path
    state_path = _resolve_state_path(config, config_file)

    if not state_path.is_file():
        typer.echo(f"No state file at {state_path} — nothing to reset.")
        return

    if not force:
        confirm = typer.confirm(f"Delete state file {state_path}?")
        if not confirm:
            typer.echo("Aborted.")
            return

    state_path.unlink()
    _ok(f"State file deleted: {state_path}")
    typer.echo("Next run will perform a full load (all datasets treated as new).\n")


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------

@app.command("history")
def history_cmd(
    config_file: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            help="Path to the loader YAML config file.",
            show_default=False,
        ),
    ] = Path("loader.yaml"),
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Maximum number of entries to show."),
    ] = 20,
) -> None:
    """Show the most recent loader run history."""
    try:
        config = LoaderConfig.from_yaml(config_file)
    except ConfigError as exc:
        typer.echo(f"Config error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)

    from eds_loader._run_log import DEFAULT_LOG_NAME, read_run_log

    log_path = (
        Path(config.run_log_file)
        if config.run_log_file and config.run_log_file != "auto"
        else config_file.parent / DEFAULT_LOG_NAME
    )

    entries = read_run_log(log_path, limit=limit)

    if not entries:
        typer.echo(f"No run history found at {log_path}.")
        typer.echo("Tip: set run_log_file: auto in your loader.yaml to enable history logging.")
        return

    typer.echo(f"\nRun history ({log_path}):\n")
    col_ts = 28
    col_mode = 14
    col_ds = 10
    col_rows = 13
    col_dur = 10
    col_st = 10

    header = (
        f"  {'Timestamp':<{col_ts}}  {'Mode':<{col_mode}}  "
        f"{'Datasets':<{col_ds}}  {'Rows Affected':<{col_rows}}  "
        f"{'Duration':<{col_dur}}  Status"
    )
    typer.echo(header)
    typer.echo("  " + "─" * (len(header) - 2))

    for e in entries:
        ts = e.get("timestamp", "")[:26]
        mode = e.get("load_mode", "")
        ds_total = e.get("datasets_total", 0)
        ds_changed = e.get("datasets_changed", 0)
        ds_skipped = e.get("datasets_skipped", 0)
        ds_txt = f"{ds_changed}✓/{ds_skipped}⊘/{ds_total}"
        rows = e.get("total_rows_affected", 0)
        dur = f"{e.get('duration_seconds', 0):.1f} s"
        st = e.get("status", "")
        symbol = _CHECK if st == "success" else _CROSS
        err = f"  ERR: {e['error'][:40]}" if e.get("error") else ""
        typer.echo(
            f"  {ts:<{col_ts}}  {mode:<{col_mode}}  "
            f"{ds_txt:<{col_ds}}  {rows:<{col_rows},}  "
            f"{dur:<{col_dur}}  {symbol} {st.upper()}{err}"
        )

    typer.echo("")


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

@app.command("diff")
def diff_cmd(
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
    """Compare source dataset sizes vs target (requires SQL or MongoDB target)."""
    try:
        config = LoaderConfig.from_yaml(config_file)
    except ConfigError as exc:
        typer.echo(f"Config error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)

    typer.echo("\nComparing source vs state for changes…\n")

    try:
        source = get_connector(config.source.kind, config.source.extra_fields())
    except (ConnectorNotFoundError, ConnectorNotInstalledError) as exc:
        _fail(f"Source connector error: {exc}")
        raise typer.Exit(code=_EXIT_CONFIG_ERROR)

    try:
        schema_meta = source.read_schema_metadata() if config.schema_required else {}
        names = list(config.tables) if config.tables else (list(schema_meta) or None)
        datasets = source.read_datasets(names=names)
    except LoadError as exc:
        _fail(f"Source read error: {exc}")
        raise typer.Exit(code=_EXIT_LOAD_ERROR)

    from eds_loader._state import dataframe_hash, load_state
    from eds_loader.loader import _resolve_state_path

    state_path = _resolve_state_path(config, config_file)
    state = load_state(state_path)

    typer.echo(f"  {'Dataset':<22}  {'Source Rows':<12}  {'Status':<10}  Hash")
    typer.echo("  " + "─" * 68)

    for name, df in datasets.items():
        h = dataframe_hash(df)
        prev = state.datasets.get(name) if state else None
        if prev and prev.source_hash == h:
            status_txt = "UNCHANGED"
        elif prev:
            status_txt = "CHANGED"
        else:
            status_txt = "NEW"
        typer.echo(
            f"  {name:<22}  {df.height:<12,}  {status_txt:<10}  {h[:16]}…"
        )

    typer.echo("")
    if not state:
        _info("No state file — all datasets will be treated as new on next run")


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


# ---------------------------------------------------------------------------
# schedule command
# ---------------------------------------------------------------------------

@app.command("schedule")
def schedule_cmd(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to loader.yaml config file."),
    ],
    status: Annotated[
        bool,
        typer.Option("--status", help="Show current schedule status."),
    ] = False,
    pause: Annotated[
        bool,
        typer.Option("--pause", help="Pause the schedule (disable without removing)."),
    ] = False,
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume a paused schedule."),
    ] = False,
    remove: Annotated[
        bool,
        typer.Option("--remove", help="Remove the scheduled task entirely."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Skip confirmation prompts."),
    ] = False,
) -> None:
    """Register, manage, or inspect the scheduled task for a loader config.

    \b
    Examples:
      eds-loader schedule -c loader.yaml              # register / update
      eds-loader schedule -c loader.yaml --status     # show current state
      eds-loader schedule -c loader.yaml --pause      # disable without removing
      eds-loader schedule -c loader.yaml --resume     # re-enable
      eds-loader schedule -c loader.yaml --remove     # delete the task
    """
    from eds_loader._scheduler import (
        build_cron_expression,
        get_schedule_status,
        pause_schedule,
        register_schedule,
        remove_schedule,
        resume_schedule,
        should_run_today,
    )

    # Load config
    try:
        cfg = LoaderConfig.from_yaml(config)
    except Exception as exc:
        _fail(str(exc))
        raise typer.Exit(_EXIT_CONFIG_ERROR)

    if cfg.schedule is None:
        _fail(
            "No 'schedule:' block found in loader.yaml. "
            "Add one, then re-run this command."
        )
        typer.echo("\nMinimal example:\n")
        typer.echo("  schedule:")
        typer.echo("    time: \"02:00\"")
        typer.echo("    timezone: Asia/Kolkata")
        typer.echo("    frequency: daily")
        raise typer.Exit(_EXIT_CONFIG_ERROR)

    config_path = config.resolve()
    sched = cfg.schedule

    # ── --status ──────────────────────────────────────────────────────────
    if status:
        st = get_schedule_status(config_path)
        typer.echo(f"\nSchedule status for {config.name}\n")
        if not st.registered:
            typer.echo(f"  {_CROSS}  Not registered — run: eds-loader schedule -c {config}")
            raise typer.Exit()

        cron = build_cron_expression(sched)
        state_label = "PAUSED" if st.paused else "ACTIVE"
        typer.echo(f"  Task name:    {st.task_name}")
        typer.echo(f"  Status:       {state_label}")
        typer.echo(f"  Cron:         {cron}")
        typer.echo(f"  Timezone:     {sched.timezone}")
        if sched.start_date:
            typer.echo(f"  Start date:   {sched.start_date}")
        if sched.end_date:
            typer.echo(f"  End date:     {sched.end_date}")
        if sched.skip_weekends:
            typer.echo("  Skip weekends: yes")
        if sched.skip_days:
            typer.echo(f"  Skip days:    {', '.join(sched.skip_days)}")
        if sched.skip_dates:
            typer.echo(f"  Skip dates:   {', '.join(sched.skip_dates)}")
        if st.last_run:
            typer.echo(f"  Last run:     {st.last_run.strftime('%Y-%m-%d %H:%M:%S')}")
        if st.next_run:
            typer.echo(f"  Next run:     {st.next_run.strftime('%Y-%m-%d %H:%M:%S')}")

        # Runtime guard check
        ok, reason = should_run_today(sched)
        typer.echo(f"\n  Today's run:  {'✓ Will run' if ok else '⊘ ' + reason}")
        typer.echo("")
        raise typer.Exit()

    # ── --pause ───────────────────────────────────────────────────────────
    if pause:
        try:
            task_name = pause_schedule(config_path)
            _ok(f"Schedule paused: {task_name}")
        except Exception as exc:
            _fail(f"Failed to pause schedule: {exc}")
            raise typer.Exit(_EXIT_LOAD_ERROR)
        raise typer.Exit()

    # ── --resume ──────────────────────────────────────────────────────────
    if resume:
        try:
            task_name = resume_schedule(config_path)
            _ok(f"Schedule resumed: {task_name}")
        except Exception as exc:
            _fail(f"Failed to resume schedule: {exc}")
            raise typer.Exit(_EXIT_LOAD_ERROR)
        raise typer.Exit()

    # ── --remove ──────────────────────────────────────────────────────────
    if remove:
        if not force:
            confirmed = typer.confirm(
                f"Remove the scheduled task for {config.name}?", default=False
            )
            if not confirmed:
                typer.echo("Aborted.")
                raise typer.Exit()
        try:
            task_name = remove_schedule(config_path)
            _ok(f"Schedule removed: {task_name}")
        except Exception as exc:
            _fail(f"Failed to remove schedule: {exc}")
            raise typer.Exit(_EXIT_LOAD_ERROR)
        raise typer.Exit()

    # ── Register (default action) ─────────────────────────────────────────
    cron = build_cron_expression(sched)

    typer.echo(f"\nReading schedule from {config.name}...\n")
    typer.echo(f"  Timezone:   {sched.timezone}")
    if sched.cron:
        typer.echo(f"  Cron:       {cron}  (custom expression)")
    else:
        typer.echo(f"  Time:       {sched.time}")
        typer.echo(f"  Frequency:  {sched.frequency}")
        if sched.on_day:
            typer.echo(f"  On day:     {sched.on_day}")
        if sched.on_date:
            typer.echo(f"  On date:    {sched.on_date} of each month")
        typer.echo(f"  Cron expr:  {cron}")
    if sched.start_date:
        typer.echo(f"  Start date: {sched.start_date}")
    if sched.end_date:
        typer.echo(f"  End date:   {sched.end_date}")
    if sched.skip_weekends:
        typer.echo("  Skip weekends: yes")
    if sched.skip_days:
        typer.echo(f"  Skip days:  {', '.join(sched.skip_days)}")
    if sched.skip_dates:
        typer.echo(f"  Skip dates: {', '.join(sched.skip_dates)}")
    if sched.retry_on_failure:
        typer.echo(
            f"  On failure: retry after {sched.retry_after_minutes} min "
            f"(max {sched.max_retries} attempts)"
        )

    import sys
    platform_name = "Windows Task Scheduler" if sys.platform == "win32" else "crontab"
    typer.echo(f"\nRegistering on {platform_name}...")

    try:
        task_name = register_schedule(sched, config_path)
    except Exception as exc:
        _fail(f"Failed to register schedule: {exc}")
        raise typer.Exit(_EXIT_LOAD_ERROR)

    typer.echo(f"  Task name:  {task_name}")
    typer.echo("")
    _ok(f"Schedule registered. Run 'eds-loader schedule -c {config.name} --status' to verify.")
    typer.echo("")
