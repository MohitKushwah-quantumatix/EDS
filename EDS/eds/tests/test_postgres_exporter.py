"""Tests for the PostgreSQL exporter.

Runs against a real PostgreSQL instance rather than a mock, for the same
reason ``test_parquet_exporter.py`` writes to a real ``tmp_path`` instead of
faking the filesystem: a mocked SQL layer would let a broken query past the
test. Each test gets its own schema so tests can run in any order, and in
parallel, without seeing each other's tables.

Requires the ``postgres`` extra (``pip install -e ".[postgres]"``) and a
reachable server; set ``EDS_TEST_POSTGRES_DSN`` to override the default of
``postgresql+psycopg://postgres:postgres@localhost:5432/eds_test``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import polars as pl
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from eds.adapters.postgres.writer import ExportError, write_dataset, write_datasets
from eds.generators.master_data import MasterData

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


def test_write_dataset_creates_the_table(pg_root_engine: Engine, pg_schema: str) -> None:
    """A dataset is written to ``<schema>.<name>``."""
    frame = pl.DataFrame({"a": [1, 2, 3]})

    location = write_dataset("sample", frame, pg_root_engine, schema=pg_schema)

    assert location == f"{pg_schema}.sample"
    assert inspect(pg_root_engine).has_table("sample", schema=pg_schema)


def test_written_data_round_trips(pg_root_engine: Engine, pg_schema: str) -> None:
    """Reading the table back yields the original frame."""
    frame = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})

    write_dataset("sample", frame, pg_root_engine, schema=pg_schema)
    restored = pl.read_database(f'SELECT * FROM "{pg_schema}"."sample"', connection=pg_root_engine)

    assert restored.sort("a").equals(frame.sort("a"))


def test_write_dataset_replaces_an_existing_table(pg_root_engine: Engine, pg_schema: str) -> None:
    """A second write overwrites the first rather than appending to it."""
    write_dataset("sample", pl.DataFrame({"a": [1, 2, 3]}), pg_root_engine, schema=pg_schema)
    write_dataset("sample", pl.DataFrame({"a": [9]}), pg_root_engine, schema=pg_schema)

    restored = pl.read_database(f'SELECT * FROM "{pg_schema}"."sample"', connection=pg_root_engine)

    assert restored["a"].to_list() == [9]


def test_write_datasets_writes_every_table(pg_root_engine: Engine, pg_schema: str) -> None:
    """Every dataset given becomes its own table."""
    datasets = {"one": pl.DataFrame({"a": [1]}), "two": pl.DataFrame({"a": [2]})}

    written = write_datasets(datasets, pg_root_engine, schema=pg_schema)

    assert set(written) == set(datasets)
    inspector = inspect(pg_root_engine)
    for name in datasets:
        assert inspector.has_table(name, schema=pg_schema)


def test_master_data_round_trips(
    master_data: MasterData, pg_root_engine: Engine, pg_schema: str
) -> None:
    """The full master-data set survives a write and read cycle."""
    write_datasets(master_data.datasets, pg_root_engine, schema=pg_schema)

    for name, frame in master_data:
        restored = pl.read_database(f'SELECT * FROM "{pg_schema}"."{name}"', connection=pg_root_engine)
        assert restored.height == frame.height, name
        assert set(restored.columns) == set(frame.columns), name


def test_export_fails_against_a_missing_schema(pg_root_engine: Engine) -> None:
    """Writing into a schema that does not exist reports an export error."""
    with pytest.raises(ExportError):
        write_dataset("sample", pl.DataFrame({"a": [1]}), pg_root_engine, schema="does_not_exist_schema")
