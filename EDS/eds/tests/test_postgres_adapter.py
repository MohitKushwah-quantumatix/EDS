"""Protocol-conformance tests for the PostgreSQL adapter.

Mirrors the ``ParquetAdapter`` assertions in ``test_platform_layout.py``
(same protocol, same shape of proof) rather than living there, since those
need a live server and the rest of that file does not.
"""

from __future__ import annotations

import inspect
import os
import uuid
from collections.abc import Iterator

import polars as pl
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from eds.adapters.base import AdapterError, DatasetReader, DatasetWriter, WriteResult
from eds.adapters.postgres.adapter import PostgresAdapter

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


def test_the_postgres_adapter_satisfies_both_protocols(pg_root_engine: Engine, pg_schema: str) -> None:
    """The second adapter conforms to the same extension points as the first."""
    adapter = PostgresAdapter.from_engine(pg_root_engine, schema=pg_schema)

    assert isinstance(adapter, DatasetWriter)
    assert isinstance(adapter, DatasetReader)
    assert adapter.name == "postgres"
    assert adapter.schema == pg_schema


def test_the_adapter_contract_mentions_no_storage_mechanics() -> None:
    """PADR-003: the protocol describes intent, not a database.

    Duplicated from ``test_platform_layout.py`` deliberately — this adapter
    is the evidence the assertion was ever meaningful, so it stays true here
    too rather than being trusted on the strength of the Parquet case alone.
    """
    for protocol, method in ((DatasetWriter, "write"), (DatasetReader, "read")):
        rendered = str(inspect.signature(getattr(protocol, method)))
        assert "Engine" not in rendered, f"{protocol.__name__}.{method} exposes a database engine"
        assert "Path" not in rendered, f"{protocol.__name__}.{method} exposes a Path"


def test_the_adapter_round_trips_a_dataset(pg_root_engine: Engine, pg_schema: str) -> None:
    """Writing then reading returns the same frame."""
    adapter = PostgresAdapter.from_engine(pg_root_engine, schema=pg_schema)
    frame = pl.DataFrame({"thing_id": [1, 2, 3]})

    written = adapter.write({"things": frame})
    read_back = adapter.read(["things"])

    assert written == (WriteResult(dataset="things", location=f"{pg_schema}.things", rows=3),)
    assert read_back["things"].sort("thing_id").equals(frame)


def test_a_write_result_records_what_landed_where(pg_root_engine: Engine, pg_schema: str) -> None:
    """Every adapter can answer what it wrote, where, and how much."""
    adapter = PostgresAdapter.from_engine(pg_root_engine, schema=pg_schema)

    results = adapter.write({"a": pl.DataFrame({"x": [1]}), "b": pl.DataFrame({"x": [1, 2]})})

    assert [result.dataset for result in results] == ["a", "b"]
    assert [result.rows for result in results] == [1, 2]
    assert [result.location for result in results] == [f"{pg_schema}.a", f"{pg_schema}.b"]


def test_a_missing_dataset_raises_an_adapter_error(pg_root_engine: Engine, pg_schema: str) -> None:
    """Adapter failures surface as AdapterError, not psycopg's own type."""
    adapter = PostgresAdapter.from_engine(pg_root_engine, schema=pg_schema)

    with pytest.raises(AdapterError):
        adapter.read(["absent"])


def test_a_write_replaces_rather_than_appends(pg_root_engine: Engine, pg_schema: str) -> None:
    """Writing the same dataset twice leaves only the second write's rows.

    Postgres-specific: unlike Parquet, a table survives between two writes
    unless the adapter explicitly replaces it, so this is the one behaviour
    worth asserting here that the Parquet suite has no equivalent for.
    """
    adapter = PostgresAdapter.from_engine(pg_root_engine, schema=pg_schema)
    adapter.write({"things": pl.DataFrame({"thing_id": [1, 2, 3]})})

    adapter.write({"things": pl.DataFrame({"thing_id": [9]})})

    assert adapter.read(["things"])["things"]["thing_id"].to_list() == [9]


def test_an_unreachable_dsn_raises_an_adapter_error() -> None:
    """A DSN that cannot even be parsed fails at construction, not on first use."""
    with pytest.raises(AdapterError):
        PostgresAdapter("not-a-valid-sqlalchemy-url")


def test_a_failed_dsn_never_puts_a_password_in_the_error_message() -> None:
    """A credential must not leak into a message a log or a bug tracker might keep.

    Regression test: the constructor used to interpolate the raw DSN with
    `!r` on failure, which included the plaintext password verbatim.
    """
    secret = "SuperSecretPassword123"
    with pytest.raises(AdapterError) as excinfo:
        PostgresAdapter(f"postgresql+nosuchdriver://postgres:{secret}@localhost:5432/eds_db")

    assert secret not in str(excinfo.value)
