"""The eds_loader Python library entry point.

This module provides :func:`load` — the single function a caller needs to
move data from a source connector to a target connector::

    from eds_loader import load
    from eds_loader.config import LoaderConfig
    from pathlib import Path

    config = LoaderConfig.from_yaml(Path("loader.yaml"))
    result = load(config)

    print(f"Done: {result.total_rows:,} rows across {len(result.tables_written)} tables")
    for table, rows in result.rows_written.items():
        print(f"  {table}: {rows:,} rows")

The CLI (``eds-loader run``) is a thin wrapper around this same function.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from eds_loader._logging import get_logger
from eds_loader.config import LoaderConfig
from eds_loader.connectors.base import Readable, Writable
from eds_loader.connectors.registry import get_connector
from eds_loader.exceptions import ConfigError, LoadError

__all__ = ["load", "LoadResult"]

logger = get_logger(__name__)


@dataclass
class LoadResult:
    """Summary of a completed loader run.

    Attributes:
        tables_written: Dataset names that were written to the target, in
            write order.
        rows_written: Dataset name → row count for each written table.
    """

    tables_written: list[str] = field(default_factory=list)
    rows_written: dict[str, int] = field(default_factory=dict)
    write_results: list[Any] = field(default_factory=list)  # list[WriteResult]

    @property
    def total_rows(self) -> int:
        """Total rows across all written tables."""
        return sum(self.rows_written.values())


def load(config: LoaderConfig) -> LoadResult:
    """Execute a loader run described by *config*.

    Steps:

    1. Instantiate source and target connectors from the registry.
    2. Verify source is :class:`~eds_loader.connectors.base.Readable` and
       target is :class:`~eds_loader.connectors.base.Writable`.
    3. Read ``schema.json`` from the source (skipped when
       ``config.schema_required`` is ``False``).
    4. Determine which tables to load (all, or the ``config.tables`` subset).
    5. Read those datasets from the source.
    6. Write them to the target (with or without constraint metadata).
    7. Return a :class:`LoadResult`.

    Args:
        config: A validated :class:`~eds_loader.config.LoaderConfig`.

    Returns:
        A :class:`LoadResult` summarising what was written.

    Raises:
        ~eds_loader.exceptions.ConnectorNotFoundError: Source or target
            ``kind`` is not in the registry.
        ~eds_loader.exceptions.ConnectorNotInstalledError: A required driver
            package is missing.
        ~eds_loader.exceptions.ConfigError: Table selection references a
            dataset not in ``schema.json``, or a connector does not support
            the role it was assigned.
        ~eds_loader.exceptions.LoadError: Runtime I/O failure during reading
            or writing.
    """
    try:
        return _load_impl(config)
    except (ConfigError, LoadError) as exc:
        logger.error("Load failed: %s", exc)
        raise
    except Exception:  # unexpected — still log before propagating
        logger.exception("Load failed with an unexpected error")
        raise


def _load_impl(config: LoaderConfig) -> LoadResult:
    source_cfg = config.source
    target_cfg = config.target

    logger.info(
        "Starting load: source=%s target=%s schema_required=%s enforce_constraints=%s",
        source_cfg.kind, target_cfg.kind, config.schema_required, config.enforce_constraints,
    )

    # Instantiate connectors via the registry (raises ConnectorNotFoundError /
    # ConnectorNotInstalledError if anything is wrong).
    source = get_connector(source_cfg.kind, source_cfg.extra_fields())
    target = get_connector(target_cfg.kind, target_cfg.extra_fields())
    logger.debug("Source connector instantiated: %s", type(source).__name__)
    logger.debug("Target connector instantiated: %s", type(target).__name__)

    # Validate role capability.
    if not isinstance(source, Readable):
        raise ConfigError(
            f"Connector {source_cfg.kind!r} does not support reading and cannot be used "
            f"as a source.  Run `eds-loader connectors` to check connector capabilities."
        )
    if not isinstance(target, Writable):
        raise ConfigError(
            f"Connector {target_cfg.kind!r} does not support writing and cannot be used "
            f"as a target.  Run `eds-loader connectors` to check connector capabilities."
        )

    # ── Schema path ───────────────────────────────────────────────────────
    if not config.schema_required:
        # Skip schema.json entirely.  Auto-discover datasets by listing
        # *.parquet files at the source.  No constraint metadata is forwarded.
        logger.info("schema_required=False — auto-discovering datasets at source")
        names_to_load: list[str] | None = list(config.tables) if config.tables else None
        datasets = source.read_datasets(names=names_to_load)
        logger.info(
            "Read %d dataset(s) from source: %s",
            len(datasets), ", ".join(datasets) or "(none)",
        )
        write_results = target.write_datasets(datasets, {})
        total_rows = sum(r.rows for r in write_results)
        logger.info(
            "Load complete: %d row(s) written across %d table(s)",
            total_rows, len(write_results),
            extra={"progress": {"stage": "done"}},
        )
        return LoadResult(
            tables_written=[r.dataset for r in write_results],
            rows_written={r.dataset: r.rows for r in write_results},
            write_results=write_results,
        )

    # ── Normal path (schema_required=True, default) ───────────────────────
    # Read the portable schema metadata (from schema.json at the source).
    logger.info("Reading schema.json from source")
    schema_metadata: dict[str, Any] = source.read_schema_metadata()
    logger.debug("schema.json contains %d dataset definition(s)", len(schema_metadata))

    # Determine the set of tables to load.
    if config.tables:
        unknown = [t for t in config.tables if t not in schema_metadata]
        if unknown:
            raise ConfigError(
                f"Table(s) not found in schema.json: {', '.join(unknown)}.\n"
                f"Available tables: {', '.join(sorted(schema_metadata))}."
            )
        names_to_load = list(config.tables)
    else:
        names_to_load = list(schema_metadata)
    logger.info("Loading %d table(s): %s", len(names_to_load), ", ".join(names_to_load))

    # Read datasets from source.
    datasets = source.read_datasets(names=names_to_load)
    logger.info(
        "Read %d dataset(s) from source, %d total row(s)",
        len(datasets), sum(df.height for df in datasets.values()),
    )
    for name, df in datasets.items():
        logger.debug("  %s: %d row(s), %d column(s)", name, df.height, df.width)

    # Build the schema metadata slice to forward to the target.
    # If enforce_constraints is False, pass an empty dict so the target
    # skips constraint logic entirely.
    if config.enforce_constraints:
        effective_metadata: dict[str, Any] = {
            k: v for k, v in schema_metadata.items() if k in datasets
        }
        logger.debug("Constraint enforcement enabled — forwarding schema metadata to target")
    else:
        effective_metadata = {}
        logger.debug("Constraint enforcement disabled — target will create plain tables")

    # Write to target.
    logger.info("Writing %d table(s) to target", len(datasets))
    write_results = target.write_datasets(datasets, effective_metadata)

    total_rows = sum(r.rows for r in write_results)
    logger.info(
        "Load complete: %d row(s) written across %d table(s)",
        total_rows, len(write_results),
        extra={"progress": {"stage": "done"}},
    )

    return LoadResult(
        tables_written=[r.dataset for r in write_results],
        rows_written={r.dataset: r.rows for r in write_results},
        write_results=write_results,
    )
