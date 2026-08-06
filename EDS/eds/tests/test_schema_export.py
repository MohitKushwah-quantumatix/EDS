"""Tests for portable schema.json export."""

from __future__ import annotations

import json
from pathlib import Path

from eds.core.schema import Dataset, ForeignKey
from eds.core.schema_export import export_schema_json
import polars as pl

_CUSTOMERS = Dataset(
    name="customers",
    columns={"customer_id": pl.Int64, "email": pl.String, "signup_at": pl.Datetime("us")},
    primary_key="customer_id",
    unique_columns=("email",),
)
_ORDERS = Dataset(
    name="orders",
    columns={"order_id": pl.Int64, "customer_id": pl.Int64, "total": pl.Float64, "placed_on": pl.Date},
    primary_key="order_id",
    foreign_keys=(ForeignKey(column="customer_id", references="customers", referenced_column="customer_id"),),
)


def test_export_writes_valid_json(tmp_path: Path) -> None:
    """The file is plain JSON, readable with only the standard library."""
    path = export_schema_json({"customers": _CUSTOMERS}, tmp_path / "schema.json")

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert "customers" in loaded


def test_primary_key_and_unique_columns_round_trip(tmp_path: Path) -> None:
    """Declared keys and uniqueness constraints appear verbatim."""
    path = export_schema_json({"customers": _CUSTOMERS}, tmp_path / "schema.json")

    entry = json.loads(path.read_text(encoding="utf-8"))["customers"]
    assert entry["primary_key"] == "customer_id"
    assert entry["unique_columns"] == ["email"]


def test_foreign_keys_round_trip(tmp_path: Path) -> None:
    """A foreign key's column, target dataset, and target column all appear."""
    path = export_schema_json({"orders": _ORDERS}, tmp_path / "schema.json")

    fk = json.loads(path.read_text(encoding="utf-8"))["orders"]["foreign_keys"][0]
    assert fk == {"column": "customer_id", "references": "customers", "referenced_column": "customer_id", "nullable": False}


def test_column_types_use_portable_names_not_polars_reprs(tmp_path: Path) -> None:
    """Types are short portable strings, not e.g. "Datetime(time_unit='us', ...)"."""
    path = export_schema_json({"orders": _ORDERS}, tmp_path / "schema.json")

    columns = json.loads(path.read_text(encoding="utf-8"))["orders"]["columns"]
    assert columns == {"order_id": "int64", "customer_id": "int64", "total": "float64", "placed_on": "date"}


def test_a_second_call_merges_rather_than_overwrites(tmp_path: Path) -> None:
    """Calling once per generation stage accumulates one complete file."""
    target = tmp_path / "schema.json"
    export_schema_json({"customers": _CUSTOMERS}, target)

    export_schema_json({"orders": _ORDERS}, target)

    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert set(loaded) == {"customers", "orders"}


def test_merge_false_replaces_the_file_entirely(tmp_path: Path) -> None:
    """merge=False discards whatever was there before."""
    target = tmp_path / "schema.json"
    export_schema_json({"customers": _CUSTOMERS}, target)

    export_schema_json({"orders": _ORDERS}, target, merge=False)

    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert set(loaded) == {"orders"}


def test_reexporting_the_same_dataset_updates_its_entry(tmp_path: Path) -> None:
    """Re-running a stage overwrites that dataset's own entry, not just adds to it."""
    target = tmp_path / "schema.json"
    export_schema_json({"customers": _CUSTOMERS}, target)
    changed = Dataset(
        name="customers",
        columns={"customer_id": pl.Int64},
        primary_key="customer_id",
    )

    export_schema_json({"customers": changed}, target)

    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["customers"]["unique_columns"] == []


def test_a_corrupt_existing_file_is_replaced_rather_than_crashing(tmp_path: Path) -> None:
    """Malformed pre-existing JSON does not stop a fresh export from succeeding."""
    target = tmp_path / "schema.json"
    target.write_text("{not valid json", encoding="utf-8")

    export_schema_json({"customers": _CUSTOMERS}, target)

    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert set(loaded) == {"customers"}


def test_creates_parent_directories(tmp_path: Path) -> None:
    """The output directory need not already exist."""
    target = tmp_path / "nested" / "output" / "schema.json"

    export_schema_json({"customers": _CUSTOMERS}, target)

    assert target.exists()
