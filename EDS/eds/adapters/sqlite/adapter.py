"""SQLite adapter for simulation history.

Stores cumulative data in a file-based SQLite database during a run.
The database lives in the project's ``.internal/`` directory, hidden from
casual view. Supports Parquet export for the daily loader.

Follows the same protocol as :class:`~eds.adapters.parquet.adapter.ParquetAdapter`
and :class:`~eds.adapters.postgres.adapter.PostgresAdapter`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from eds.adapters.base import AdapterError, WriteResult

__all__ = ["SQLITE_ADAPTER_NAME", "SQLiteAdapter"]

#: Registry name for this adapter.
SQLITE_ADAPTER_NAME = "sqlite"

#: Default database filename inside the project's ``.internal/`` directory.
_DEFAULT_DB_NAME = "simulation.db"


class SQLiteAdapter:
    """Stores datasets in a file-based SQLite database.

    Satisfies both :class:`~eds.adapters.base.DatasetWriter` and
    :class:`~eds.adapters.base.DatasetReader`.

    Each write replaces the table in full, matching the Parquet writer's
    "regenerate, don't patch" behaviour.

    Args:
        db_path: Path to the SQLite database file. Created if absent.
            Defaults to ``.internal/simulation.db`` inside the project.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = Path(".internal") / _DEFAULT_DB_NAME
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine: Engine = create_engine(f"sqlite:///{db_path}")

    @property
    def name(self) -> str:
        """Return the adapter's registry name."""
        return SQLITE_ADAPTER_NAME

    @property
    def engine(self) -> Engine:
        """Return the SQLAlchemy engine."""
        return self._engine

    def write(self, datasets: Mapping[str, pl.DataFrame]) -> tuple[WriteResult, ...]:
        """Write every dataset, replacing any existing table.

        Also stores the Polars schema in a ``_schema`` metadata table so
        types can be restored exactly when the data is read back. Existing
        schema entries are preserved; only the tables being written in this
        call are updated.

        Args:
            datasets: Dataset name to frame.

        Returns:
            One result per dataset, carrying the table name and row count.

        Raises:
            AdapterError: If any dataset cannot be written.
        """
        try:
            with self._engine.begin() as conn:
                for name, frame in datasets.items():
                    conn.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
                    frame.write_database(name, connection=self._engine, if_table_exists="replace")
                conn.execute(text('CREATE TABLE IF NOT EXISTS "_schema" (table_name TEXT, column_name TEXT, dtype TEXT)'))
                for name, frame in datasets.items():
                    conn.execute(text('DELETE FROM "_schema" WHERE table_name = :table_name'), {"table_name": name})
                    schema_rows = [
                        {"table_name": name, "column_name": col, "dtype": str(dtype)}
                        for col, dtype in frame.schema.items()
                    ]
                    conn.execute(text('INSERT INTO "_schema" VALUES (:table_name, :column_name, :dtype)'), schema_rows)
        except (SQLAlchemyError, pl.exceptions.PolarsError) as exc:
            raise AdapterError(f"Could not write to SQLite: {exc}") from exc
        return tuple(
            WriteResult(dataset=name, location=name, rows=datasets[name].height)
            for name in datasets
        )

    def read(self, names: Iterable[str]) -> dict[str, pl.DataFrame]:
        """Read the named datasets from SQLite.

        Uses pandas as an intermediary to handle SQLite's loose typing,
        then converts to Polars using the stored schema to preserve exact
        dtypes.

        Args:
            names: Dataset names to load.

        Returns:
            Dataset name to frame, with types restored from the stored schema.

        Raises:
            AdapterError: If any dataset is missing or unreadable.
        """
        import pandas as pd

        result: dict[str, pl.DataFrame] = {}
        stored_schema: dict[str, dict[str, str]] = {}
        try:
            with self._engine.connect() as conn:
                schema_rows = conn.execute(text('SELECT table_name, column_name, dtype FROM "_schema"')).fetchall()
            for row in schema_rows:
                stored_schema.setdefault(row[0], {})[row[1]] = row[2]
        except Exception:
            pass

        for name in names:
            try:
                with self._engine.connect() as conn:
                    df_pd = pd.read_sql(f'SELECT * FROM "{name}"', conn)
                df = pl.from_pandas(df_pd)
                if name in stored_schema:
                    df = self._apply_stored_schema(df, stored_schema[name])
                result[name] = df
            except Exception as exc:
                raise AdapterError(f"Could not read {name!r} from SQLite: {exc}") from exc
        return result

    def _apply_stored_schema(self, df: pl.DataFrame, schema: dict[str, str]) -> pl.DataFrame:
        """Apply a stored schema to a DataFrame read from SQLite.

        Date and datetime columns are converted from strings or integers
        using ``str.to_date()``, ``str.to_datetime()``, or ``cast()`` to
        handle SQLite's loose typing. SQLAlchemy may store datetimes as
        TEXT on some platforms and as INTEGER microseconds on others.
        """
        date_cols: list[pl.Expr] = []
        datetime_cols: list[pl.Expr] = []
        scalar_casts: dict[str, pl.DataType] = {}

        for col, dtype_str in schema.items():
            if col not in df.columns:
                continue
            current_dtype = df.schema[col]
            target_dtype = self._coerce_dtype(dtype_str)
            if target_dtype == pl.Date and current_dtype == pl.String:
                date_cols.append(pl.col(col).str.to_date())
            elif target_dtype == pl.Datetime:
                if current_dtype == pl.String:
                    datetime_cols.append(pl.col(col).str.to_datetime())
                elif current_dtype in (pl.Int64, pl.Int32):
                    datetime_cols.append(pl.col(col).cast(pl.Datetime("us")))
            elif target_dtype != current_dtype:
                scalar_casts[col] = target_dtype

        if date_cols:
            df = df.with_columns(date_cols)
        if datetime_cols:
            df = df.with_columns(datetime_cols)
        if scalar_casts:
            try:
                df = df.cast(scalar_casts)
            except Exception:
                pass
        return df

    def read_all(self) -> dict[str, pl.DataFrame]:
        """Read every table currently in the database.

        Returns:
            Dataset name to frame for every table present, with types restored.
        """
        import pandas as pd

        with self._engine.connect() as conn:
            tables = [
                row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            ]
        return self.read(tables)

    def _cast_date_columns(self, df: pl.DataFrame) -> pl.DataFrame:
        """Cast SQLite date/datetime strings to proper Polars types."""
        date_like_types = {pl.Date, pl.Datetime, pl.Time}
        casts: list[pl.Expr] = []
        for col, dtype in df.schema.items():
            if dtype == pl.String:
                sample = df[col].drop_nulls().head(1)
                if sample.is_empty():
                    continue
                sample_val = sample.item()
                if isinstance(sample_val, str) and self._looks_like_date(sample_val):
                    casts.append(pl.col(col).str.to_date())
                elif isinstance(sample_val, str) and self._looks_like_datetime(sample_val):
                    casts.append(pl.col(col).str.to_datetime())
        return df.with_columns(casts) if casts else df

    @staticmethod
    def _looks_like_date(value: str) -> bool:
        if not isinstance(value, str):
            return False
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                datetime.strptime(value, fmt)
                return True
            except ValueError:
                continue
        return False

    @staticmethod
    def _looks_like_datetime(value: str) -> bool:
        if not isinstance(value, str):
            return False
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S.%f",
        ):
            try:
                datetime.strptime(value, fmt)
                return True
            except ValueError:
                continue
        return False

    def export_to_parquet(self, output_dir: Path, target_date: str | None = None) -> dict[str, Path]:
        """Export datasets to Parquet, optionally filtered by date.

        Args:
            output_dir: Directory to write Parquet files into.
            target_date: ISO date string (``"2026-01-01"``). When given,
                only rows whose ``created_at`` matches this date are exported.
                When ``None``, all rows are exported.

        Returns:
            Dataset name to written path.

        Raises:
            AdapterError: If any dataset cannot be exported.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}
        try:
            with self._engine.connect() as conn:
                tables = [
                    row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
                ]
            for name in tables:
                df = pl.read_database(f'SELECT * FROM "{name}"', connection=self._engine)
                if target_date is not None:
                    date_col = self._pick_date_column(df)
                    if date_col is None:
                        continue
                    col_type = str(df.schema[date_col]).lower()
                    if "datetime" in col_type:
                        filtered = df.filter(pl.col(date_col).dt.date().cast(pl.String) == target_date)
                    else:
                        filtered = df.filter(pl.col(date_col).cast(pl.String) == target_date)
                    if filtered.is_empty():
                        continue
                    df = filtered
                path = output_dir / f"{name}.parquet"
                df.write_parquet(path, compression="snappy")
                written[name] = path
        except (SQLAlchemyError, pl.exceptions.PolarsError) as exc:
            raise AdapterError(f"Could not export to Parquet: {exc}") from exc
        return written

    def drop_all(self) -> None:
        """Drop every table in the database."""
        with self._engine.begin() as conn:
            tables = [
                row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            ]
            for name in tables:
                conn.execute(text(f'DROP TABLE IF EXISTS "{name}"'))

    @staticmethod
    def _pick_date_column(df: pl.DataFrame) -> str | None:
        preferences = (
            "created_at",
            "order_date",
            "registration_date",
            "admission_date",
            "admitted_at",
            "scheduled_date",
            "recorded_at",
            "prescribed_at",
            "onset_date",
            "performed_at",
            "reported_at",
            "administered_at",
            "referral_date",
            "billing_date",
            "submitted_date",
            "processed_date",
            "follow_up_date",
            "hire_date",
            "certification_date",
            "effective_date",
            "start_date",
        )
        for name in preferences:
            if name in df.columns:
                dtype = str(df.schema[name]).lower()
                if "date" in dtype or "datetime" in dtype:
                    return name
        for col, dtype in df.schema.items():
            if "date" in str(dtype).lower() or "datetime" in str(dtype).lower():
                return col
        return None

    @staticmethod
    def _coerce_dtype(dtype_str: str) -> pl.DataType:
        """Convert a Polars dtype string back to a Polars DataType."""
        lower = dtype_str.lower()
        if lower.startswith("int"):
            return pl.Int64
        if lower.startswith("float"):
            return pl.Float64
        if lower == "boolean":
            return pl.Boolean
        if lower == "string" or lower == "str":
            return pl.String
        if lower == "date":
            return pl.Date
        if lower.startswith("datetime"):
            return pl.Datetime("us")
        if lower == "time":
            return pl.Time
        return pl.String
