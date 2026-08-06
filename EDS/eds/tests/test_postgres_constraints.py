"""Tests that PADR-018's constraints are real, not merely declared.

Every other Postgres test file proves data survives a round trip. This file
proves the database itself will refuse to store data that breaks a primary
key, a foreign key, or a declared uniqueness rule -- the difference between
"the DDL mentions a constraint" and "the constraint holds."

This is also the one test file that reaches into
``eds.runners.retail.postgres_schema`` for ``RETAIL_DATASET_SCHEMAS``: the
adapter and writer under test are domain-agnostic (PADR-003), so proving
constraint enforcement for a real dataset needs a real caller-supplied
schema mapping, exactly as production code would supply one.

Rows are built generically from each dataset's declared columns
(:func:`_sample_row`) rather than hand-written with literal column names, so
a test here does not silently stop testing anything if a generator's schema
changes shape later.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import polars as pl
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from eds.adapters.postgres.schema_ddl import write_order
from eds.adapters.postgres.writer import write_dataset, write_datasets
from eds.core.schema import Dataset
from eds.generators.master_data import MasterData
from eds.runners.retail.postgres_schema import RETAIL_DATASET_SCHEMAS

pytestmark = pytest.mark.postgres

_DEFAULT_DSN = "postgresql+psycopg://postgres:postgres@localhost:5432/eds_test"


def _dataset(name: str) -> Dataset:
    return RETAIL_DATASET_SCHEMAS[name]


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


def _sample_value(dtype: pl.DataType) -> object:
    """A harmless placeholder value for one column, keyed off its dtype."""
    base = dtype.base_type()
    if base is pl.Int64:
        return 0
    if base is pl.Float64:
        return 0.0
    if base is pl.Boolean:
        return False
    if base is pl.Date:
        return "2026-01-01"
    if base is pl.Datetime:
        return "2026-01-01 00:00:00"
    return "x"


def _sample_row(dataset: Dataset, **overrides: object) -> dict[str, object]:
    """Build one row satisfying every column, with specific values overridden."""
    row = {name: _sample_value(dtype) for name, dtype in dataset.columns.items()}
    row.update(overrides)
    return row


def _insert(conn: Connection, schema: str, dataset: Dataset, row: dict[str, object]) -> None:
    """Insert one row via a parameterised statement built from its keys."""
    columns = ", ".join(f'"{c}"' for c in row)
    placeholders = ", ".join(f":{c}" for c in row)
    conn.execute(text(f'INSERT INTO "{schema}"."{dataset.name}" ({columns}) VALUES ({placeholders})'), row)


def test_write_order_puts_referenced_tables_first() -> None:
    """countries is referenced by states, so it must be written before it."""
    subset = {name: _dataset(name) for name in ("states", "countries", "cities")}

    order = write_order(subset)

    assert order.index("countries") < order.index("states") < order.index("cities")


def test_a_duplicate_primary_key_is_rejected(pg_root_engine: Engine, pg_schema: str) -> None:
    """Two rows with the same primary key cannot both be inserted."""
    dataset = _dataset("coupon_types")
    write_dataset(
        "coupon_types", pl.DataFrame(schema=dataset.polars_schema()), pg_root_engine, schema=pg_schema, dataset_schema=dataset
    )

    with pg_root_engine.connect() as conn:
        _insert(conn, pg_schema, dataset, _sample_row(dataset, coupon_type_id=1))
        conn.commit()
        with pytest.raises(IntegrityError):
            _insert(conn, pg_schema, dataset, _sample_row(dataset, coupon_type_id=1))
            conn.commit()


def test_a_foreign_key_violation_is_rejected(pg_root_engine: Engine, pg_schema: str) -> None:
    """A row pointing at a customer that does not exist is refused."""
    customers, loyalty = _dataset("customers"), _dataset("customer_loyalty")
    write_datasets(
        {
            "customers": pl.DataFrame(schema=customers.polars_schema()),
            "customer_loyalty": pl.DataFrame(schema=loyalty.polars_schema()),
        },
        pg_root_engine,
        schema=pg_schema,
        schemas=RETAIL_DATASET_SCHEMAS,
    )

    with pg_root_engine.connect() as conn:
        with pytest.raises(IntegrityError):
            _insert(conn, pg_schema, loyalty, _sample_row(loyalty, loyalty_id=1, customer_id=999999))
            conn.commit()


def test_a_foreign_key_accepts_a_row_that_does_reference_something_real(
    pg_root_engine: Engine, pg_schema: str
) -> None:
    """The same constraint that rejects a dangling reference accepts a real one."""
    customers, loyalty = _dataset("customers"), _dataset("customer_loyalty")
    write_datasets(
        {
            "customers": pl.DataFrame(schema=customers.polars_schema()),
            "customer_loyalty": pl.DataFrame(schema=loyalty.polars_schema()),
        },
        pg_root_engine,
        schema=pg_schema,
        schemas=RETAIL_DATASET_SCHEMAS,
    )

    with pg_root_engine.connect() as conn:
        _insert(conn, pg_schema, customers, _sample_row(customers, customer_id=1))
        conn.commit()
        _insert(conn, pg_schema, loyalty, _sample_row(loyalty, loyalty_id=1, customer_id=1))
        conn.commit()

    restored = pl.read_database(f'SELECT * FROM "{pg_schema}".customer_loyalty', connection=pg_root_engine)
    assert restored.height == 1


def test_a_unique_column_violation_is_rejected(pg_root_engine: Engine, pg_schema: str) -> None:
    """Two suppliers with the same supplier_code cannot both be stored.

    suppliers references countries, states, and cities, so all three are
    written first -- the same dependency order write_datasets enforces
    automatically when given schemas=RETAIL_DATASET_SCHEMAS.
    """
    names = ("countries", "states", "cities", "suppliers")
    write_datasets(
        {name: pl.DataFrame(schema=_dataset(name).polars_schema()) for name in names},
        pg_root_engine,
        schema=pg_schema,
        schemas=RETAIL_DATASET_SCHEMAS,
    )
    suppliers, countries, states, cities = (_dataset(n) for n in ("suppliers", "countries", "states", "cities"))

    with pg_root_engine.connect() as conn:
        _insert(conn, pg_schema, countries, _sample_row(countries, country_id=0))
        conn.commit()
        _insert(conn, pg_schema, states, _sample_row(states, state_id=0, country_id=0))
        conn.commit()
        _insert(conn, pg_schema, cities, _sample_row(cities, city_id=0, state_id=0, country_id=0))
        conn.commit()
        _insert(conn, pg_schema, suppliers, _sample_row(suppliers, supplier_id=1, supplier_code="SUP-DUPE"))
        conn.commit()
        with pytest.raises(IntegrityError):
            _insert(conn, pg_schema, suppliers, _sample_row(suppliers, supplier_id=2, supplier_code="SUP-DUPE"))
            conn.commit()


def test_master_data_round_trips_with_constraints_enforced(
    master_data: MasterData, pg_root_engine: Engine, pg_schema: str
) -> None:
    """The full master-data batch writes in dependency order with real DDL."""
    write_datasets(master_data.datasets, pg_root_engine, schema=pg_schema, schemas=RETAIL_DATASET_SCHEMAS)

    inspector = inspect(pg_root_engine)
    for name in master_data.datasets:
        dataset = _dataset(name)
        pk = inspector.get_pk_constraint(name, schema=pg_schema)
        assert pk["constrained_columns"] == [dataset.primary_key], name

        fks = inspector.get_foreign_keys(name, schema=pg_schema)
        declared = {fk.column for fk in dataset.foreign_keys}
        found = {col for fk in fks for col in fk["constrained_columns"]}
        assert found == declared, name


def test_an_unknown_dataset_falls_back_to_inferred_schema(pg_root_engine: Engine, pg_schema: str) -> None:
    """A frame under a name outside RETAIL_DATASET_SCHEMAS gets no DDL."""
    write_dataset(
        "scratch_notes", pl.DataFrame({"note": ["hello"]}), pg_root_engine, schema=pg_schema
    )

    inspector = inspect(pg_root_engine)
    assert inspector.get_pk_constraint("scratch_notes", schema=pg_schema)["constrained_columns"] == []


def test_omitting_schemas_skips_ddl_even_for_a_known_dataset_name(pg_root_engine: Engine, pg_schema: str) -> None:
    """Without a schemas mapping, even a real dataset name gets no DDL."""
    write_dataset("countries", pl.DataFrame({"a": [1]}), pg_root_engine, schema=pg_schema)

    restored = pl.read_database(f'SELECT * FROM "{pg_schema}".countries', connection=pg_root_engine)
    assert restored.columns == ["a"]
