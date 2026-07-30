"""Tests for the schema-conformant frame helpers."""

from __future__ import annotations

import polars as pl
import pytest

from eds.domain.geography.schema import COUNTRIES
from eds.domain.master_data import MASTER_DATA_DATASETS, dataset_by_name, dataset_names
from eds.generators.frames import build_frame, empty_frame, format_code

VALID_COLUMNS: dict[str, list[object]] = {
    "country_id": [1],
    "country_code": ["US"],
    "country_code_3": ["USA"],
    "country_name": ["United States"],
    "currency_code": ["USD"],
    "phone_code": ["+1"],
    "region": ["North America"],
}


def test_build_frame_applies_declared_schema() -> None:
    """The built frame has the declared column order and dtypes."""
    frame = build_frame(COUNTRIES, VALID_COLUMNS)

    assert frame.columns == list(COUNTRIES.column_names)
    assert frame.schema["country_id"] == pl.Int64()
    assert frame.height == 1


def test_build_frame_rejects_missing_columns() -> None:
    """A missing column fails at construction, not at export time."""
    columns = {key: value for key, value in VALID_COLUMNS.items() if key != "region"}

    with pytest.raises(ValueError, match="missing columns"):
        build_frame(COUNTRIES, columns)


def test_build_frame_rejects_unexpected_columns() -> None:
    """An undeclared column is refused rather than silently written."""
    with pytest.raises(ValueError, match="unexpected columns"):
        build_frame(COUNTRIES, {**VALID_COLUMNS, "population": [1]})


def test_build_frame_rejects_ragged_columns() -> None:
    """Columns of differing length indicate a generator bug."""
    with pytest.raises(ValueError, match="differing lengths"):
        build_frame(COUNTRIES, {**VALID_COLUMNS, "region": ["A", "B"]})


def test_empty_frame_has_the_schema_and_no_rows() -> None:
    """An empty frame still carries the declared schema."""
    frame = empty_frame(COUNTRIES)

    assert frame.height == 0
    assert frame.columns == list(COUNTRIES.column_names)


@pytest.mark.parametrize(
    ("prefix", "number", "width", "expected"),
    [("SKU", 1, 8, "SKU-00000001"), ("WH", 42, 4, "WH-0042"), ("CAT", 123456, 6, "CAT-123456")],
)
def test_format_code(prefix: str, number: int, width: int, expected: str) -> None:
    """Codes are zero-padded to the requested width."""
    assert format_code(prefix, number, width) == expected


def test_format_code_rejects_negative_numbers() -> None:
    """A negative identifier is a programming error."""
    with pytest.raises(ValueError, match="must not be negative"):
        format_code("SKU", -1)


def test_registry_lists_the_fourteen_documented_outputs() -> None:
    """F001 declares exactly fourteen output datasets.

    ``return_reasons`` was added for F009, which requires the return reason
    vocabulary to come from master data.
    """
    assert len(MASTER_DATA_DATASETS) == 14
    assert set(dataset_names()) == {
        "countries",
        "states",
        "cities",
        "categories",
        "brands",
        "suppliers",
        "products",
        "warehouses",
        "inventory",
        "shipping_methods",
        "payment_methods",
        "tax_codes",
        "coupon_types",
        "return_reasons",
    }


def test_registry_is_in_dependency_order() -> None:
    """Every dataset appears after the datasets it references."""
    seen: set[str] = set()
    for dataset in MASTER_DATA_DATASETS:
        for foreign_key in dataset.foreign_keys:
            # Self-references such as the category tree are allowed.
            assert foreign_key.references in seen or foreign_key.references == dataset.name
        seen.add(dataset.name)


def test_dataset_file_names_match_the_specification() -> None:
    """Each dataset maps to the documented Parquet file name."""
    assert dataset_by_name("products").file_name == "products.parquet"


def test_unknown_dataset_lookup_raises() -> None:
    """Looking up an unregistered dataset fails with a helpful message."""
    with pytest.raises(KeyError, match="Unknown dataset"):
        dataset_by_name("customers")
