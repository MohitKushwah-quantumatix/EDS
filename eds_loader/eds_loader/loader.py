"""The eds_loader Python library entry point.

This module provides :func:`load` — the single function a caller needs to
move data from a source connector to a target connector::

    from eds_loader import load
    from eds_loader.config import LoaderConfig
    from pathlib import Path

    config = LoaderConfig.from_yaml(Path("loader.yaml"))
    result = load(config)

    print(f"Done: {result.total_rows:,} rows across {len(result.tables_written)} tables")

Load modes
----------
``load_mode: full`` (default)
    Every run drops and recreates all target tables/collections.

``load_mode: incremental``
    Hash-based change detection + upsert for changed datasets only.
    Supports ``delete_mode: keep | soft | hard``.

Additional features
-------------------
- Row-level validation (``on_validation_error: warn | fail | quarantine``)
- Schema drift detection (``schema_drift: warn | fail | ignore``)
- Parallel dataset loading (``parallelism: N``)
- Chunked writing (``batch_size: N``)
- Run metrics JSON file (``metrics_file``)
- Append-only run log JSONL (``run_log_file``)
- Notifications on failure/success (``notifications`` block)
- Retry on failure (``retry_count`` / ``retry_delay``)
- ENV-var interpolation in config YAML (``${VAR}``)
"""

from __future__ import annotations

import concurrent.futures
import datetime
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eds_loader._logging import get_logger
from eds_loader._metrics import RunMetrics, write_metrics
from eds_loader._notifications import dispatch_notifications
from eds_loader._run_log import DEFAULT_LOG_NAME, append_run_log
from eds_loader._schema_drift import check_drift
from eds_loader._state import (
    DatasetState,
    RunState,
    dataframe_hash,
    load_state,
    save_state,
    schema_fingerprint,
)
from eds_loader._validation import apply_validation
from eds_loader.config import LoaderConfig
from eds_loader.connectors.base import Appendable, Readable, Upsertable, Writable
from eds_loader.connectors.registry import get_connector
from eds_loader.exceptions import (
    ConfigError,
    ConnectorNotFoundError,
    ConnectorNotInstalledError,
    LoadError,
)

__all__ = ["load", "LoadResult"]

logger = get_logger(__name__)


def _read_schema_metadata(config: "LoaderConfig", source: Any) -> dict[str, Any]:
    """Read schema.json, honouring ``config.schema_path`` if set.

    Priority:
    1. ``schema_path`` in config → read directly from that explicit file path.
    2. Fallback → call ``source.read_schema_metadata()`` (connector's default).

    Args:
        config: The loader config.
        source: The source connector instance.

    Returns:
        Parsed schema dict (table name → column map).
    """
    if config.schema_path:
        import json
        p = Path(config.schema_path)
        if not p.is_file():
            raise LoadError(
                f"schema_path not found: {p}\n"
                "Check that the path is correct and the file exists."
            )
        logger.info("Reading schema.json from explicit schema_path: %s", p)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            raise LoadError(f"Cannot read schema.json at {p}: {exc}") from exc
    return source.read_schema_metadata()


@dataclass
class LoadResult:
    """Summary of a completed loader run."""

    tables_written: list[str] = field(default_factory=list)
    rows_written: dict[str, int] = field(default_factory=dict)
    write_results: list[Any] = field(default_factory=list)
    rows_inserted: dict[str, int] = field(default_factory=dict)
    rows_updated: dict[str, int] = field(default_factory=dict)
    tables_skipped: list[str] = field(default_factory=list)
    load_mode: str = "full"

    @property
    def total_rows(self) -> int:
        return sum(self.rows_written.values())


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def load(config: LoaderConfig, config_path: Path | None = None) -> LoadResult:
    """Execute a loader run described by *config*.

    Args:
        config: A validated :class:`~eds_loader.config.LoaderConfig`.
        config_path: Optional path to the YAML file (used to derive state
            file and metrics file paths when relative).

    Returns:
        A :class:`LoadResult` summarising what was written.
    """
    # ── Schedule skip-date guard ─────────────────────────────────────────
    # When a schedule: block is present, check skip rules before doing any work.
    # This handles skip_dates, skip_weekends, skip_days, and date range.
    if config.schedule is not None:
        from eds_loader._scheduler import should_run_today
        ok, reason = should_run_today(config.schedule)
        if not ok:
            logger.info(reason)
            return LoadResult(load_mode=config.load_mode)
    # ─────────────────────────────────────────────────────────────────

    max_attempts = 1 + config.retry_count
    last_exc: BaseException | None = None
    t_start = time.monotonic()

    metrics = RunMetrics(
        config_file=str(config_path) if config_path else "config",
        load_mode=config.load_mode,
    )

    for attempt in range(1, max_attempts + 1):
        try:
            if config.load_mode == "incremental":
                result = _incremental_load_impl(config, config_path)
            elif config.load_mode == "append":
                result = _append_load_impl(config)
            else:
                result = _load_impl(config)

            # ── Success ──────────────────────────────────────────────────
            elapsed = time.monotonic() - t_start
            metrics.finish_success(elapsed, result.total_rows)
            for r in result.write_results:
                rows_ins = getattr(r, "rows_inserted", r.rows)
                rows_upd = getattr(r, "rows_updated", 0)
                metrics.record_dataset(
                    r.dataset, "upserted" if rows_upd else "written",
                    rows_written=r.rows, rows_inserted=rows_ins,
                    rows_updated=rows_upd, location=r.location,
                )
            for name in result.tables_skipped:
                metrics.record_dataset(name, "skipped")

            _post_run(config, config_path, metrics, "success")
            return result

        except (ConfigError, ConnectorNotFoundError, ConnectorNotInstalledError) as exc:
            elapsed = time.monotonic() - t_start
            metrics.finish_failure(elapsed, str(exc))
            _post_run(config, config_path, metrics, "failed")
            raise

        except LoadError as exc:
            last_exc = exc
            logger.error("Load failed (attempt %d/%d): %s", attempt, max_attempts, exc)
            if attempt < max_attempts:
                logger.info("Retrying in %d second(s)…", config.retry_delay)
                time.sleep(config.retry_delay)

        except Exception as exc:
            last_exc = exc
            logger.exception("Unexpected error (attempt %d/%d)", attempt, max_attempts)
            if attempt < max_attempts:
                time.sleep(config.retry_delay)

    # All attempts exhausted
    elapsed = time.monotonic() - t_start
    err_msg = str(last_exc) if last_exc else f"Load failed after {max_attempts} attempt(s)"
    metrics.finish_failure(elapsed, err_msg)
    _post_run(config, config_path, metrics, "failed")

    if isinstance(last_exc, LoadError):
        raise last_exc
    raise LoadError(f"Load failed after {max_attempts} attempt(s)") from last_exc


def _post_run(
    config: LoaderConfig,
    config_path: Path | None,
    metrics: RunMetrics,
    status: str,
) -> None:
    """Write metrics, append run log, send notifications — all non-fatal."""
    base = config_path.parent if config_path else Path(".")

    # Metrics JSON file
    if config.metrics_file:
        mf = Path(config.metrics_file) if config.metrics_file != "auto" \
            else base / "run_metrics.json"
        try:
            write_metrics(metrics, mf)
            logger.info("Metrics written → %s", mf)
        except Exception as exc:
            logger.warning("Could not write metrics file: %s", exc)

    # Append-only run log
    if config.run_log_file is not None:
        rl = Path(config.run_log_file) if config.run_log_file != "auto" \
            else base / DEFAULT_LOG_NAME
        append_run_log(metrics, rl)

    # Notifications
    if config.notifications:
        m = metrics.to_dict()
        subject = (
            f"EDS Loader {'✓ SUCCESS' if status == 'success' else '✗ FAILED'} "
            f"— {m['config']} ({m['load_mode']})"
        )
        body = (
            f"Status:   {status.upper()}\n"
            f"Duration: {m['duration_seconds']:.1f}s\n"
            f"Rows:     {m['total_rows_affected']:,}\n"
            + (f"Error:    {m['error']}\n" if m.get("error") else "")
        )
        dispatch_notifications(config.notifications, status, subject, body, m)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_state_path(config: LoaderConfig, config_path: Path | None = None) -> Path:
    if config.state_file:
        return Path(config.state_file)
    if config_path:
        return config_path.parent / f".{config_path.stem}_state.json"
    return Path(".eds_loader_state.json")


def _chunk_df(df: Any, batch_size: int | None) -> list[Any]:
    """Split *df* into chunks of at most *batch_size* rows."""
    if batch_size is None or df.height <= batch_size:
        return [df]
    return [df.slice(i, batch_size) for i in range(0, df.height, batch_size)]


def _apply_encryption(
    datasets: dict[str, Any],
    config: "LoaderConfig",
) -> dict[str, Any]:
    """Encrypt configured columns in each dataset before writing.

    If ``config.column_encryption`` is ``None`` returns *datasets* unchanged
    (zero overhead for configs without encryption).

    Args:
        datasets: Dataset name -> Polars DataFrame mapping.
        config:   The active :class:`LoaderConfig`.

    Returns:
        Mapping with encrypted DataFrames for configured tables, all others
        passed through unchanged.

    Raises:
        LoadError: If the key env-var is missing or a column is not found.
    """
    enc_cfg = config.column_encryption
    if enc_cfg is None or not enc_cfg.tables:
        return datasets

    from cryptography.fernet import Fernet
    from eds_loader._encryption import encrypt_dataframe, load_key

    key = load_key(enc_cfg.key_env)
    fernet = Fernet(key)

    result = dict(datasets)  # shallow copy — only replace encrypted tables
    for table_name, columns in enc_cfg.tables.items():
        if table_name not in result:
            logger.debug(
                "[encryption] Table %r not in loaded datasets — skipping", table_name
            )
            continue
        logger.info("[encryption] Encrypting %d column(s) in %r", len(columns), table_name)
        result[table_name] = encrypt_dataframe(result[table_name], columns, fernet)
    return result


# ---------------------------------------------------------------------------
# Full load
# ---------------------------------------------------------------------------

def _load_impl(config: LoaderConfig) -> LoadResult:
    source = get_connector(config.source.kind, config.source.extra_fields())
    target = get_connector(config.target.kind, config.target.extra_fields())

    if not isinstance(source, Readable):
        raise ConfigError(f"Connector {config.source.kind!r} does not support reading.")
    if not isinstance(target, Writable):
        raise ConfigError(f"Connector {config.target.kind!r} does not support writing.")

    schema_metadata: dict[str, Any] = {}
    if config.schema_required:
        schema_metadata = _read_schema_metadata(config, source)

    names_to_load: list[str] | None
    if config.tables:
        if schema_metadata:
            unknown = [t for t in config.tables if t not in schema_metadata]
            if unknown:
                raise ConfigError(
                    f"Table(s) not found in schema.json: {', '.join(unknown)}."
                )
        names_to_load = list(config.tables)
    else:
        names_to_load = list(schema_metadata) if schema_metadata else None

    datasets = source.read_datasets(names=names_to_load)
    logger.info("Read %d dataset(s) from source", len(datasets))

    # Validation
    rejected_dir = Path(config.rejected_dir)
    validated: dict[str, Any] = {}
    for name, df in datasets.items():
        schema_entry = schema_metadata.get(name, {})
        validated[name] = apply_validation(
            name, df, schema_entry, config.on_validation_error, rejected_dir
        )

    effective_metadata = (
        {k: v for k, v in schema_metadata.items() if k in validated}
        if config.enforce_constraints else {}
    )

    # Encrypt configured columns before writing
    validated = _apply_encryption(validated, config)

    # Parallel or sequential write
    if config.parallelism > 1:
        write_results = _parallel_write(target, validated, effective_metadata, config)
    else:
        write_results = target.write_datasets(validated, effective_metadata)

    total_rows = sum(r.rows for r in write_results)
    logger.info("Load complete: %d row(s) written", total_rows,
                extra={"progress": {"stage": "done"}})

    return LoadResult(
        tables_written=[r.dataset for r in write_results],
        rows_written={r.dataset: r.rows for r in write_results},
        write_results=write_results,
        load_mode="full",
    )


def _parallel_write(target: Any, datasets: dict[str, Any],
                    schema_metadata: dict[str, Any],
                    config: LoaderConfig) -> list[Any]:
    """Write datasets in parallel using ThreadPoolExecutor."""
    results: list[Any] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.parallelism) as ex:
        futures = {
            ex.submit(target.write_datasets, {name: df}, schema_metadata): name
            for name, df in datasets.items()
        }
        for fut in concurrent.futures.as_completed(futures):
            name = futures[fut]
            try:
                batch_results = fut.result()
                results.extend(batch_results)
            except Exception as exc:
                raise LoadError(f"Parallel write failed for dataset {name!r}: {exc}") from exc
    return results


# ---------------------------------------------------------------------------
# Incremental load
# ---------------------------------------------------------------------------

def _incremental_load_impl(
    config: LoaderConfig, config_path: Path | None = None
) -> LoadResult:
    source = get_connector(config.source.kind, config.source.extra_fields())
    target = get_connector(config.target.kind, config.target.extra_fields())

    if not isinstance(source, Readable):
        raise ConfigError(f"Connector {config.source.kind!r} cannot be used as a source.")
    if not isinstance(target, Upsertable):
        raise ConfigError(
            f"Connector {config.target.kind!r} does not support incremental upsert."
        )

    schema_metadata: dict[str, Any] = {}
    if config.schema_required:
        schema_metadata = _read_schema_metadata(config, source)

    names_to_load: list[str] | None
    if config.tables:
        if schema_metadata:
            unknown = [t for t in config.tables if t not in schema_metadata]
            if unknown:
                raise ConfigError(
                    f"Table(s) not found in schema.json: {', '.join(unknown)}."
                )
        names_to_load = list(config.tables)
    else:
        names_to_load = list(schema_metadata) if schema_metadata else None

    state_path = _resolve_state_path(config, config_path)
    prev_state = load_state(state_path)
    is_first_run = prev_state is None
    if is_first_run:
        logger.info("No state file — performing initial full upsert (%s)", state_path)
    else:
        logger.info("State loaded from %s (last run: %s)", state_path, prev_state.last_run)

    datasets = source.read_datasets(names=names_to_load)
    logger.info("Read %d dataset(s) from source", len(datasets))

    # Validation + drift detection, then partition changed/skipped
    rejected_dir = Path(config.rejected_dir)
    changed: dict[str, Any] = {}
    skipped: list[str] = []
    hashes: dict[str, str] = {}
    schema_fps: dict[str, dict[str, str]] = {}

    for name, df in datasets.items():
        schema_entry = schema_metadata.get(name, {})

        # Schema drift check (only when state exists)
        if prev_state and config.schema_drift != "ignore":
            prev_ds = prev_state.datasets.get(name)
            stored_fp = prev_ds.schema_fingerprint if prev_ds else None
            check_drift(name, df, stored_fp, config.schema_drift)

        # Validation
        df = apply_validation(name, df, schema_entry, config.on_validation_error, rejected_dir)

        h = dataframe_hash(df)
        hashes[name] = h
        schema_fps[name] = schema_fingerprint(df)
        prev_ds = prev_state.datasets.get(name) if prev_state else None
        if prev_ds and prev_ds.source_hash == h:
            logger.info("[%s] Hash unchanged — skipping", name)
            skipped.append(name)
        else:
            reason = "first run" if prev_ds is None else "hash changed"
            logger.info("[%s] %s — will upsert %d row(s)", name, reason, df.height)
            changed[name] = df

    if not changed:
        logger.info("All %d dataset(s) unchanged — nothing to write", len(skipped),
                    extra={"progress": {"stage": "done"}})
        _save_incremental_state(state_path, config, datasets, hashes, schema_fps,
                                upsert_results=[], skipped=list(datasets), prev_state=prev_state)
        return LoadResult(tables_written=[], rows_written={}, write_results=[],
                          tables_skipped=skipped, load_mode="incremental")

    effective_metadata = (
        {k: v for k, v in schema_metadata.items() if k in changed}
        if config.enforce_constraints and schema_metadata else {}
    )

    # Encrypt configured columns before writing
    changed = _apply_encryption(changed, config)

    upsert_results = target.upsert_datasets(changed, effective_metadata)

    # Handle delete_mode
    if config.delete_mode != "keep" and isinstance(target, Writable):
        _apply_delete_mode(target, config, schema_metadata, datasets, changed)

    _save_incremental_state(state_path, config, datasets, hashes, schema_fps,
                            upsert_results=upsert_results, skipped=skipped, prev_state=prev_state)
    logger.info("State saved → %s", state_path)

    total = sum(r.rows for r in upsert_results)
    logger.info("Incremental load complete: %d row(s) affected", total,
                extra={"progress": {"stage": "done"}})

    return LoadResult(
        tables_written=[r.dataset for r in upsert_results],
        rows_written={r.dataset: r.rows for r in upsert_results},
        write_results=upsert_results,
        rows_inserted={r.dataset: r.rows_inserted for r in upsert_results},
        rows_updated={r.dataset: r.rows_updated for r in upsert_results},
        tables_skipped=skipped,
        load_mode="incremental",
    )


# ---------------------------------------------------------------------------
# Append load
# ---------------------------------------------------------------------------

def _append_load_impl(config: LoaderConfig) -> LoadResult:
    """Append-only load — inserts rows without ever dropping or updating existing data.

    Every run:
    1. Read all datasets from source.
    2. Validate each dataset (same as full/incremental).
    3. ``CREATE TABLE IF NOT EXISTS`` on target (first run only in practice).
    4. Bulk-INSERT all rows unconditionally.

    No state file is needed. The target table grows permanently with every run.

    Args:
        config: A validated :class:`~eds_loader.config.LoaderConfig` with
                ``load_mode: append``.

    Returns:
        :class:`LoadResult` with ``load_mode='append'``.

    Raises:
        ~eds_loader.exceptions.ConfigError: If the target connector does not
            implement :class:`~eds_loader.connectors.base.Appendable`.
        ~eds_loader.exceptions.LoadError: On any read or write failure.
    """
    source = get_connector(config.source.kind, config.source.extra_fields())
    target = get_connector(config.target.kind, config.target.extra_fields())

    if not isinstance(source, Readable):
        raise ConfigError(f"Connector {config.source.kind!r} cannot be used as a source.")
    if not isinstance(target, Appendable):
        raise ConfigError(
            f"Connector {config.target.kind!r} does not support append mode. "
            "Use a SQL-family connector (postgres, mysql, mssql, sqlite) or "
            "MongoDB as the target."
        )

    schema_metadata: dict[str, Any] = {}
    if config.schema_required:
        schema_metadata = _read_schema_metadata(config, source)

    names_to_load: list[str] | None
    if config.tables:
        if schema_metadata:
            unknown = [t for t in config.tables if t not in schema_metadata]
            if unknown:
                raise ConfigError(
                    f"Table(s) not found in schema.json: {', '.join(unknown)}."
                )
        names_to_load = list(config.tables)
    else:
        names_to_load = list(schema_metadata) if schema_metadata else None

    datasets = source.read_datasets(names=names_to_load)
    logger.info("Read %d dataset(s) from source for append", len(datasets))

    # Validation — same rules as full/incremental
    rejected_dir = Path(config.rejected_dir)
    validated: dict[str, Any] = {}
    for name, df in datasets.items():
        schema_entry = schema_metadata.get(name, {})
        validated[name] = apply_validation(
            name, df, schema_entry, config.on_validation_error, rejected_dir
        )

    effective_metadata = (
        {k: v for k, v in schema_metadata.items() if k in validated}
        if config.enforce_constraints else {}
    )

    # Encrypt configured columns before writing
    validated = _apply_encryption(validated, config)

    append_results = target.append_datasets(validated, effective_metadata)

    total_rows = sum(r.rows_appended for r in append_results)
    logger.info(
        "Append load complete: %d row(s) inserted across %d dataset(s)",
        total_rows, len(append_results),
        extra={"progress": {"stage": "done"}},
    )

    return LoadResult(
        tables_written=[r.dataset for r in append_results],
        rows_written={r.dataset: r.rows_appended for r in append_results},
        write_results=append_results,
        load_mode="append",
    )


def _apply_delete_mode(
    target: Any,
    config: LoaderConfig,
    schema_metadata: dict[str, Any],
    all_datasets: dict[str, Any],
    changed: dict[str, Any],
) -> None:
    """Apply soft or hard deletes for rows removed from source."""
    for name, df in changed.items():
        schema_entry = schema_metadata.get(name, {})
        pk_col: str | None = schema_entry.get("primary_key")
        if not pk_col:
            continue

        if config.delete_mode == "soft":
            # Add _eds_deleted_at column with null for active rows
            # (the target keeps all rows; deleted ones get a timestamp on next run)
            logger.debug("[%s] delete_mode=soft: marking active rows", name)
            # This is a best-effort hint; full soft-delete requires target-side query
            continue

        if config.delete_mode == "hard":
            # Build set of PKs currently in source
            source_pks = set(df[pk_col].to_list())
            logger.info("[%s] delete_mode=hard: %d source PKs", name, len(source_pks))
            # Delegate to target connector's delete_missing method if available
            delete_fn = getattr(target, "delete_missing_rows", None)
            if callable(delete_fn):
                try:
                    deleted = delete_fn(name, pk_col, source_pks, schema_metadata)
                    logger.info("[%s] Deleted %d row(s) not in source", name, deleted)
                except Exception as exc:
                    logger.warning("[%s] Hard delete failed: %s", name, exc)
            else:
                logger.warning(
                    "[%s] delete_mode=hard: target connector does not support "
                    "delete_missing_rows() — skipped", name
                )


def _save_incremental_state(
    state_path: Path,
    config: LoaderConfig,
    datasets: dict[str, Any],
    hashes: dict[str, str],
    schema_fps: dict[str, dict[str, str]],
    upsert_results: list[Any],
    skipped: list[str],
    prev_state: RunState | None,
) -> None:
    now = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    upsert_map = {r.dataset: r for r in upsert_results}
    new_datasets: dict[str, DatasetState] = {}

    for name, df in datasets.items():
        h = hashes[name]
        fp = schema_fps.get(name, {})
        if name in skipped:
            prev_ds = prev_state.datasets.get(name) if prev_state else None
            new_datasets[name] = DatasetState(
                source_hash=h, rows_at_source=df.height,
                rows_inserted=0, rows_updated=0, skipped=True,
                last_changed=prev_ds.last_changed if prev_ds else now,
                schema_fingerprint=fp,
            )
        else:
            r = upsert_map.get(name)
            new_datasets[name] = DatasetState(
                source_hash=h, rows_at_source=df.height,
                rows_inserted=r.rows_inserted if r else 0,
                rows_updated=r.rows_updated if r else 0,
                skipped=False, last_changed=now,
                schema_fingerprint=fp,
            )

    state = RunState(
        version=1,
        config_file=str(state_path.name),
        last_run=now, mode="incremental",
        datasets=new_datasets,
    )
    try:
        save_state(state_path, state)
    except LoadError as exc:
        logger.warning("Could not save state file: %s", exc)
