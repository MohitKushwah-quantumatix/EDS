"""Tests for the load() function — role checks, table validation, and result shape."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from eds_loader.config import LoaderConfig
from eds_loader.connectors.base import WriteResult, Readable, Writable
from eds_loader.connectors.registry import CONNECTORS, ConnectorSpec, register_connector
from eds_loader.exceptions import ConfigError
from eds_loader.loader import LoadResult, load


# ---------------------------------------------------------------------------
# Fixtures — registry isolation + mock connectors
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_registry():
    """Restore CONNECTORS after each test."""
    original = dict(CONNECTORS)
    yield
    CONNECTORS.clear()
    CONNECTORS.update(original)


def _minimal_schema() -> dict[str, Any]:
    return {
        "customers": {
            "columns": {"customer_id": "int64"},
            "primary_key": "customer_id",
            "unique_columns": [],
            "foreign_keys": [],
        },
        "orders": {
            "columns": {"order_id": "int64", "customer_id": "int64"},
            "primary_key": "order_id",
            "unique_columns": [],
            "foreign_keys": [
                {
                    "column": "customer_id",
                    "references": "customers",
                    "referenced_column": "customer_id",
                    "nullable": False,
                }
            ],
        },
    }


def _make_readable_connector(schema: dict | None = None, datasets: dict | None = None):
    """Return a mock that satisfies the Readable protocol."""
    conn = MagicMock(spec=Readable)
    conn.read_schema_metadata.return_value = schema if schema is not None else _minimal_schema()
    conn.read_datasets.return_value = datasets if datasets is not None else {
        "customers": pl.DataFrame({"customer_id": [1, 2]}),
        "orders": pl.DataFrame({"order_id": [10], "customer_id": [1]}),
    }
    return conn


def _make_writable_connector(results: list[WriteResult] | None = None):
    """Return a mock that satisfies the Writable protocol."""
    conn = MagicMock(spec=Writable)
    conn.write_datasets.return_value = results if results is not None else [
        WriteResult(dataset="customers", location="customers", rows=2),
        WriteResult(dataset="orders", location="orders", rows=1),
    ]
    return conn


def _register_pair(source_conn, target_conn):
    """Register a source and target connector, return a matching LoaderConfig."""
    source_cls = MagicMock(return_value=source_conn)
    target_cls = MagicMock(return_value=target_conn)

    register_connector(
        "mock_source",
        ConnectorSpec(
            connector_class=source_cls,
            can_read=True,
            can_write=False,
            description="mock source",
        ),
    )
    register_connector(
        "mock_target",
        ConnectorSpec(
            connector_class=target_cls,
            can_read=False,
            can_write=True,
            description="mock target",
        ),
    )
    config = LoaderConfig(
        source={"kind": "mock_source"},
        target={"kind": "mock_target"},
    )
    return config


# ---------------------------------------------------------------------------
# load() — happy path
# ---------------------------------------------------------------------------

def test_load_returns_load_result() -> None:
    source = _make_readable_connector()
    target = _make_writable_connector()
    config = _register_pair(source, target)

    result = load(config)

    assert isinstance(result, LoadResult)
    assert set(result.tables_written) == {"customers", "orders"}
    assert result.total_rows == 3


def test_load_passes_schema_metadata_to_target_when_enforce_true() -> None:
    source = _make_readable_connector()
    target = _make_writable_connector()
    config = _register_pair(source, target)

    load(config)

    _, kwargs = target.write_datasets.call_args
    # schema_metadata must be non-empty when enforce_constraints=True
    schema_arg = target.write_datasets.call_args[0][1]
    assert len(schema_arg) > 0


def test_load_passes_empty_metadata_when_enforce_false() -> None:
    source = _make_readable_connector()
    target = _make_writable_connector()
    config = _register_pair(source, target)
    config = config.model_copy(update={"enforce_constraints": False})

    load(config)

    schema_arg = target.write_datasets.call_args[0][1]
    assert schema_arg == {}


# ---------------------------------------------------------------------------
# load() — table selection
# ---------------------------------------------------------------------------

def test_load_passes_all_tables_when_tables_empty() -> None:
    source = _make_readable_connector()
    target = _make_writable_connector()
    config = _register_pair(source, target)

    load(config)

    names_arg = source.read_datasets.call_args[1]["names"]
    assert set(names_arg) == {"customers", "orders"}


def test_load_respects_table_subset() -> None:
    source = _make_readable_connector(
        datasets={"customers": pl.DataFrame({"customer_id": [1]})}
    )
    target = _make_writable_connector(
        results=[WriteResult(dataset="customers", location="customers", rows=1)]
    )
    config = _register_pair(source, target)
    config = config.model_copy(update={"tables": ["customers"]})

    result = load(config)

    names_arg = source.read_datasets.call_args[1]["names"]
    assert names_arg == ["customers"]
    assert result.tables_written == ["customers"]


def test_load_unknown_table_in_selection_raises_config_error() -> None:
    source = _make_readable_connector()
    target = _make_writable_connector()
    config = _register_pair(source, target)
    config = config.model_copy(update={"tables": ["no_such_table"]})

    with pytest.raises(ConfigError, match="no_such_table"):
        load(config)


# ---------------------------------------------------------------------------
# load() — role validation
# ---------------------------------------------------------------------------

def test_load_raises_config_error_when_source_not_readable() -> None:
    """A write-only connector cannot be used as a source."""
    write_only_cls = MagicMock(return_value=MagicMock(spec=Writable))
    register_connector(
        "write_only",
        ConnectorSpec(connector_class=write_only_cls, can_read=False, can_write=True),
    )
    register_connector(
        "mock_target2",
        ConnectorSpec(
            connector_class=MagicMock(return_value=_make_writable_connector()),
            can_read=False,
            can_write=True,
        ),
    )
    config = LoaderConfig(
        source={"kind": "write_only"},
        target={"kind": "mock_target2"},
    )
    with pytest.raises(ConfigError, match="does not support reading"):
        load(config)


def test_load_raises_config_error_when_target_not_writable() -> None:
    """A read-only connector cannot be used as a target."""
    read_only_cls = MagicMock(return_value=_make_readable_connector())
    register_connector(
        "mock_source2",
        ConnectorSpec(connector_class=read_only_cls, can_read=True, can_write=False),
    )
    read_only_target_cls = MagicMock(return_value=MagicMock(spec=Readable))
    register_connector(
        "read_only_target",
        ConnectorSpec(
            connector_class=read_only_target_cls, can_read=True, can_write=False
        ),
    )
    config = LoaderConfig(
        source={"kind": "mock_source2"},
        target={"kind": "read_only_target"},
    )
    with pytest.raises(ConfigError, match="does not support writing"):
        load(config)


# ---------------------------------------------------------------------------
# LoadResult properties
# ---------------------------------------------------------------------------

def test_load_result_total_rows() -> None:
    result = LoadResult(
        tables_written=["a", "b"],
        rows_written={"a": 100, "b": 50},
    )
    assert result.total_rows == 150


def test_load_result_empty() -> None:
    result = LoadResult()
    assert result.total_rows == 0
    assert result.tables_written == []
