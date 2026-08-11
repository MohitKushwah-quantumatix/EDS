"""Local filesystem connector — source and target.

Reads Parquet datasets and ``schema.json`` from a local directory (source
role) and writes Parquet datasets back to a local directory (target role).

This is the simplest connector and serves as the baseline for testing all
others.  No optional dependencies are required — :mod:`polars` is already a
core dependency of ``eds_loader``.

Self-registration
-----------------
The :func:`~eds_loader.connectors.registry.register_connector` call at the
bottom of this module runs once when the module is first imported.
``eds_loader/__init__.py`` imports this module so that ``local_fs`` is always
available whenever the package is used — from the CLI or as a library.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from eds_loader.connectors.base import WriteResult
from eds_loader.connectors.registry import ConnectorSpec, register_connector
from eds_loader.exceptions import LoadError

__all__ = ["LocalFSConnector"]

_SCHEMA_FILE = "schema.json"


class LocalFSConnector:
    """Read and write EDS Parquet datasets on the local filesystem.

    Acts as both a **source** (satisfies
    :class:`~eds_loader.connectors.base.Readable`) and a **target**
    (satisfies :class:`~eds_loader.connectors.base.Writable`).

    Config fields
    -------------
    ``path`` (required)
        Path to the directory containing (or to receive) ``.parquet`` files
        and ``schema.json``.

    Example config::

        source:
          kind: local_fs
          path: ./output

        target:
          kind: local_fs
          path: ./landing

    Args:
        path: Local directory path.  Passed directly from the ``path`` field
            in the connector config section.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    # ------------------------------------------------------------------
    # Readable interface
    # ------------------------------------------------------------------

    def read_schema_metadata(self) -> dict[str, Any]:
        """Read ``schema.json`` from the source directory.

        Returns:
            Parsed schema metadata — a dict mapping dataset name to its
            ``columns``, ``primary_key``, ``unique_columns``, and
            ``foreign_keys`` entries.

        Raises:
            ~eds_loader.exceptions.LoadError: If ``schema.json`` is absent,
                unreadable, or contains invalid JSON.
        """
        schema_path = self._path / _SCHEMA_FILE
        if not schema_path.is_file():
            raise LoadError(
                f"schema.json not found at {schema_path}.\n"
                "Run `eds generate <stage>` to produce it alongside the Parquet files, "
                "or check that the source path is correct."
            )
        try:
            text = schema_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise LoadError(f"Cannot read schema.json at {schema_path}: {exc}") from exc

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LoadError(
                f"schema.json at {schema_path} contains invalid JSON: {exc}"
            ) from exc

    def read_datasets(
        self,
        names: list[str] | None = None,
    ) -> dict[str, pl.DataFrame]:
        """Read Parquet datasets from the source directory.

        Args:
            names: Dataset names to read (without the ``.parquet``
                extension).  ``None`` reads every ``.parquet`` file found
                in the directory.

        Returns:
            Dict mapping dataset name to its Polars DataFrame.

        Raises:
            ~eds_loader.exceptions.LoadError: If the directory cannot be
                listed, or if any named dataset file is missing or
                unreadable.
        """
        if names is None:
            try:
                parquet_files = sorted(self._path.glob("*.parquet"))
            except OSError as exc:
                raise LoadError(
                    f"Cannot list directory {self._path}: {exc}"
                ) from exc
            names = [f.stem for f in parquet_files]

        result: dict[str, pl.DataFrame] = {}
        for name in names:
            file_path = self._path / f"{name}.parquet"
            if not file_path.is_file():
                raise LoadError(
                    f"Dataset {name!r} not found at {file_path}.\n"
                    "Check the source path or re-run EDS generation."
                )
            try:
                result[name] = pl.read_parquet(file_path)
            except Exception as exc:
                raise LoadError(
                    f"Cannot read dataset {name!r} from {file_path}: {exc}"
                ) from exc
        return result

    # ------------------------------------------------------------------
    # Writable interface
    # ------------------------------------------------------------------

    def write_datasets(
        self,
        datasets: dict[str, pl.DataFrame],
        schema_metadata: dict[str, Any],
    ) -> list[WriteResult]:
        """Write Parquet datasets to the target directory.

        Creates the target directory if it does not exist.  Existing
        ``.parquet`` files with the same name are overwritten (full
        replace — NFR-3).

        If ``schema_metadata`` is non-empty, ``schema.json`` is also
        written (merging with any existing file) so that this directory
        can be used directly as a ``local_fs`` source in a subsequent
        load — enabling chained loads without re-running EDS generation.

        Args:
            datasets: Dataset name to Polars DataFrame.
            schema_metadata: Schema entry dict to write alongside the
                Parquet files.  Pass an empty dict to skip writing
                ``schema.json``.

        Returns:
            One :class:`~eds_loader.connectors.base.WriteResult` per
            dataset, in iteration order of *datasets*.

        Raises:
            ~eds_loader.exceptions.LoadError: If the directory cannot be
                created or any file cannot be written.
        """
        try:
            self._path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LoadError(
                f"Cannot create target directory {self._path}: {exc}"
            ) from exc

        results: list[WriteResult] = []
        for name, df in datasets.items():
            file_path = self._path / f"{name}.parquet"
            try:
                df.write_parquet(file_path)
            except Exception as exc:
                raise LoadError(
                    f"Cannot write dataset {name!r} to {file_path}: {exc}"
                ) from exc
            results.append(
                WriteResult(dataset=name, location=str(file_path), rows=df.height)
            )

        if schema_metadata:
            self._write_schema_json(schema_metadata)

        return results

    def _write_schema_json(self, schema_metadata: dict[str, Any]) -> None:
        """Merge *schema_metadata* into ``schema.json`` at the target path."""
        schema_path = self._path / _SCHEMA_FILE
        existing: dict[str, Any] = {}
        if schema_path.is_file():
            try:
                existing = json.loads(schema_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}

        existing.update(schema_metadata)
        try:
            schema_path.write_text(
                json.dumps(existing, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            raise LoadError(
                f"Cannot write schema.json to {schema_path}: {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Self-registration — runs once when this module is first imported.
# ---------------------------------------------------------------------------
register_connector(
    "local_fs",
    ConnectorSpec(
        connector_class=LocalFSConnector,
        required_packages=[],  # polars is a core dep — no extra install needed
        install_extra="",
        can_read=True,
        can_write=True,
        description="Local filesystem — reads/writes Parquet files from/to a local directory.",
    ),
)
