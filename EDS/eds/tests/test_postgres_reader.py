"""Tests for reading previously exported PostgreSQL datasets.

See ``test_postgres_exporter.py`` for why this runs against a real server
and how the per-test schema is provisioned; the fixtures are duplicated
locally rather than shared to keep each test file readable on its own,
matching how ``eds.adapters.parquet``'s two test files each define their own
``tmp_path``-based expectations.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import polars as pl
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from eds.adapters.postgres.reader import DatasetNotFoundError, read_dataset, read_datasets
from eds.adapters.postgres.writer import write_datasets

pytestmark = pytest.mark.postgres

_DEFAULT_DSN = "postgresql+psycopg://postgres:postgres@localhost:5432/eds_test"


@pytest.fixture(scope="module")
def pg_root_engine() -> Iterator[Engine]:
    """An engine for the test database, disposed once the module is done."""
    dsn = os.environ.get("EDS_TEST_POSTGRES_DSN", _DEFAULT_DSN)
    try:
        engine = create_engine(dsn)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any connection failure skips, doesn't fail the suite
        pytest.skip(f"PostgreSQL is not reachable at {dsn!r}: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture
def pg_schema(pg_root_engine: Engine) -> Iterator[str]:
    """A schema unique to this test, dropped afterwards."""
    schema = f"eds_test_{uuid.uuid4().hex[:12]}"
    with pg_root_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    yield schema
    with pg_root_engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def test_round_trip_through_the_writer(pg_root_engine: Engine, pg_schema: str) -> None:
    """A dataset written by the exporter reads back unchanged."""
    frame = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    write_datasets({"sample": frame}, pg_root_engine, schema=pg_schema)

    restored = read_dataset("sample", pg_root_engine, schema=pg_schema)

    assert restored.sort("a").equals(frame.sort("a"))


def test_read_datasets_preserves_request_order(pg_root_engine: Engine, pg_schema: str) -> None:
    """Datasets come back keyed in the order requested."""
    write_datasets(
        {"one": pl.DataFrame({"a": [1]}), "two": pl.DataFrame({"a": [2]})}, pg_root_engine, schema=pg_schema
    )

    assert list(read_datasets(["two", "one"], pg_root_engine, schema=pg_schema)) == ["two", "one"]


def test_missing_dataset_names_the_next_step(pg_root_engine: Engine, pg_schema: str) -> None:
    """The error tells the user what to do."""
    with pytest.raises(DatasetNotFoundError, match="write stage"):
        read_dataset("cities", pg_root_engine, schema=pg_schema)


def test_read_datasets_fails_on_the_first_missing_entry(pg_root_engine: Engine, pg_schema: str) -> None:
    """A partially populated schema is still an error."""
    write_datasets({"countries": pl.DataFrame({"a": [1]})}, pg_root_engine, schema=pg_schema)

    with pytest.raises(DatasetNotFoundError, match="'states'"):
        read_datasets(["countries", "states"], pg_root_engine, schema=pg_schema)
