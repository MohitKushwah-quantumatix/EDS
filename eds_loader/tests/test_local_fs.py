"""Tests for LocalFSConnector — registration, read, write, round-trip, integration."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from eds_loader.connectors.local_fs import LocalFSConnector
from eds_loader.connectors.registry import CONNECTORS
from eds_loader.exceptions import LoadError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_schema() -> dict:
    return {
        "customers": {
            "columns": {"customer_id": "int64", "name": "string"},
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


@pytest.fixture()
def sample_datasets() -> dict[str, pl.DataFrame]:
    return {
        "customers": pl.DataFrame(
            {"customer_id": [1, 2, 3], "name": ["Alice", "Bob", "Carol"]}
        ),
        "orders": pl.DataFrame({"order_id": [10, 11], "customer_id": [1, 2]}),
    }


@pytest.fixture()
def source_dir(tmp_path: Path, sample_schema: dict, sample_datasets: dict) -> Path:
    """A populated source directory — schema.json + two parquet files."""
    for name, df in sample_datasets.items():
        df.write_parquet(tmp_path / f"{name}.parquet")
    (tmp_path / "schema.json").write_text(
        json.dumps(sample_schema, indent=2), encoding="utf-8"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_local_fs_is_registered() -> None:
    """Importing eds_loader registers 'local_fs' in the connector registry."""
    import eds_loader  # noqa: F401 — triggers __init__.py which imports local_fs
    assert "local_fs" in CONNECTORS


def test_local_fs_can_read_and_write() -> None:
    spec = CONNECTORS["local_fs"]
    assert spec.can_read is True
    assert spec.can_write is True


def test_local_fs_has_no_required_packages() -> None:
    """local_fs needs no extra pip install — polars is a core dep."""
    spec = CONNECTORS["local_fs"]
    assert spec.required_packages == []


def test_local_fs_connector_class_is_correct_type() -> None:
    spec = CONNECTORS["local_fs"]
    assert spec.connector_class is LocalFSConnector


# ---------------------------------------------------------------------------
# read_schema_metadata — happy path
# ---------------------------------------------------------------------------

def test_read_schema_metadata_returns_correct_dict(
    source_dir: Path, sample_schema: dict
) -> None:
    conn = LocalFSConnector(path=source_dir)
    meta = conn.read_schema_metadata()
    assert meta == sample_schema


def test_read_schema_metadata_contains_expected_keys(source_dir: Path) -> None:
    conn = LocalFSConnector(path=source_dir)
    meta = conn.read_schema_metadata()
    assert "customers" in meta
    assert "primary_key" in meta["customers"]
    assert "columns" in meta["customers"]


# ---------------------------------------------------------------------------
# read_schema_metadata — error cases
# ---------------------------------------------------------------------------

def test_read_schema_metadata_missing_raises_load_error(tmp_path: Path) -> None:
    conn = LocalFSConnector(path=tmp_path)
    with pytest.raises(LoadError, match="schema.json not found"):
        conn.read_schema_metadata()


def test_read_schema_metadata_corrupt_json_raises_load_error(tmp_path: Path) -> None:
    (tmp_path / "schema.json").write_text("{not: valid json!!!", encoding="utf-8")
    conn = LocalFSConnector(path=tmp_path)
    with pytest.raises(LoadError, match="invalid JSON"):
        conn.read_schema_metadata()


def test_read_schema_metadata_empty_json_raises_load_error(tmp_path: Path) -> None:
    (tmp_path / "schema.json").write_text("", encoding="utf-8")
    conn = LocalFSConnector(path=tmp_path)
    with pytest.raises(LoadError):
        conn.read_schema_metadata()


# ---------------------------------------------------------------------------
# read_datasets — names=None (scan directory)
# ---------------------------------------------------------------------------

def test_read_datasets_none_reads_all_parquet_files(
    source_dir: Path, sample_datasets: dict
) -> None:
    conn = LocalFSConnector(path=source_dir)
    result = conn.read_datasets(names=None)
    assert set(result) == set(sample_datasets)


def test_read_datasets_none_ignores_non_parquet_files(tmp_path: Path) -> None:
    """Only .parquet files are returned when names=None."""
    pl.DataFrame({"a": [1]}).write_parquet(tmp_path / "data.parquet")
    (tmp_path / "readme.txt").write_text("ignore me", encoding="utf-8")
    (tmp_path / "schema.json").write_text("{}", encoding="utf-8")
    conn = LocalFSConnector(path=tmp_path)
    result = conn.read_datasets(names=None)
    assert set(result) == {"data"}


def test_read_datasets_none_returns_correct_row_counts(
    source_dir: Path, sample_datasets: dict
) -> None:
    conn = LocalFSConnector(path=source_dir)
    result = conn.read_datasets(names=None)
    for name, df in sample_datasets.items():
        assert result[name].height == df.height, f"Row count mismatch for {name!r}"


def test_read_datasets_none_empty_directory_returns_empty_dict(tmp_path: Path) -> None:
    conn = LocalFSConnector(path=tmp_path)
    result = conn.read_datasets(names=None)
    assert result == {}


# ---------------------------------------------------------------------------
# read_datasets — explicit names
# ---------------------------------------------------------------------------

def test_read_datasets_explicit_names_reads_only_named(source_dir: Path) -> None:
    conn = LocalFSConnector(path=source_dir)
    result = conn.read_datasets(names=["customers"])
    assert set(result) == {"customers"}


def test_read_datasets_explicit_preserves_column_values(
    source_dir: Path, sample_datasets: dict
) -> None:
    conn = LocalFSConnector(path=source_dir)
    result = conn.read_datasets(names=["customers"])
    expected = sample_datasets["customers"]
    assert result["customers"].to_dict(as_series=False) == expected.to_dict(as_series=False)


def test_read_datasets_missing_file_raises_load_error(source_dir: Path) -> None:
    conn = LocalFSConnector(path=source_dir)
    with pytest.raises(LoadError, match="'no_such_table'"):
        conn.read_datasets(names=["no_such_table"])


def test_read_datasets_one_missing_in_multi_raises_load_error(source_dir: Path) -> None:
    """Even one missing dataset in a multi-name list raises LoadError."""
    conn = LocalFSConnector(path=source_dir)
    with pytest.raises(LoadError):
        conn.read_datasets(names=["customers", "ghost_table"])


# ---------------------------------------------------------------------------
# write_datasets
# ---------------------------------------------------------------------------

def test_write_datasets_creates_directory(tmp_path: Path, sample_datasets: dict) -> None:
    target = tmp_path / "deep" / "nested" / "dir"
    assert not target.exists()
    conn = LocalFSConnector(path=target)
    conn.write_datasets(sample_datasets, schema_metadata={})
    assert target.is_dir()


def test_write_datasets_writes_parquet_files(
    tmp_path: Path, sample_datasets: dict
) -> None:
    conn = LocalFSConnector(path=tmp_path)
    conn.write_datasets(sample_datasets, schema_metadata={})
    for name in sample_datasets:
        assert (tmp_path / f"{name}.parquet").is_file(), f"Missing {name}.parquet"


def test_write_datasets_returns_one_result_per_dataset(
    tmp_path: Path, sample_datasets: dict
) -> None:
    conn = LocalFSConnector(path=tmp_path)
    results = conn.write_datasets(sample_datasets, schema_metadata={})
    assert len(results) == len(sample_datasets)
    assert {r.dataset for r in results} == set(sample_datasets)


def test_write_datasets_result_rows_match_dataframe_height(
    tmp_path: Path, sample_datasets: dict
) -> None:
    conn = LocalFSConnector(path=tmp_path)
    results = conn.write_datasets(sample_datasets, schema_metadata={})
    rows_by_name = {r.dataset: r.rows for r in results}
    for name, df in sample_datasets.items():
        assert rows_by_name[name] == df.height


def test_write_datasets_result_location_points_to_existing_file(
    tmp_path: Path, sample_datasets: dict
) -> None:
    conn = LocalFSConnector(path=tmp_path)
    results = conn.write_datasets(sample_datasets, schema_metadata={})
    for result in results:
        assert Path(result.location).is_file()


def test_write_datasets_overwrites_existing_file(tmp_path: Path) -> None:
    """Full replace — second write wins."""
    conn = LocalFSConnector(path=tmp_path)
    old_df = pl.DataFrame({"id": [1, 2, 3]})
    new_df = pl.DataFrame({"id": [99]})
    conn.write_datasets({"data": old_df}, schema_metadata={})
    conn.write_datasets({"data": new_df}, schema_metadata={})
    on_disk = pl.read_parquet(tmp_path / "data.parquet")
    assert on_disk["id"].to_list() == [99]


# ---------------------------------------------------------------------------
# schema.json on write
# ---------------------------------------------------------------------------

def test_write_datasets_writes_schema_json_when_metadata_nonempty(
    tmp_path: Path, sample_datasets: dict, sample_schema: dict
) -> None:
    conn = LocalFSConnector(path=tmp_path)
    conn.write_datasets(sample_datasets, schema_metadata=sample_schema)
    schema_path = tmp_path / "schema.json"
    assert schema_path.is_file()
    written = json.loads(schema_path.read_text(encoding="utf-8"))
    assert "customers" in written
    assert "orders" in written


def test_write_datasets_skips_schema_json_when_metadata_empty(
    tmp_path: Path, sample_datasets: dict
) -> None:
    conn = LocalFSConnector(path=tmp_path)
    conn.write_datasets(sample_datasets, schema_metadata={})
    assert not (tmp_path / "schema.json").exists()


def test_write_datasets_merges_schema_json_with_existing(
    tmp_path: Path, sample_datasets: dict, sample_schema: dict
) -> None:
    """schema.json at the target is merged — pre-existing tables are not lost."""
    pre_existing = {
        "old_table": {
            "columns": {"id": "int64"},
            "primary_key": "id",
            "unique_columns": [],
            "foreign_keys": [],
        }
    }
    (tmp_path / "schema.json").write_text(
        json.dumps(pre_existing), encoding="utf-8"
    )
    conn = LocalFSConnector(path=tmp_path)
    conn.write_datasets(sample_datasets, schema_metadata=sample_schema)
    merged = json.loads((tmp_path / "schema.json").read_text(encoding="utf-8"))
    assert "old_table" in merged      # pre-existing survives
    assert "customers" in merged      # new tables added
    assert "orders" in merged


def test_write_datasets_corrupt_existing_schema_json_is_replaced(
    tmp_path: Path, sample_datasets: dict, sample_schema: dict
) -> None:
    """A corrupt schema.json at the target is silently replaced, not raised."""
    (tmp_path / "schema.json").write_text("{bad json", encoding="utf-8")
    conn = LocalFSConnector(path=tmp_path)
    conn.write_datasets(sample_datasets, schema_metadata=sample_schema)  # must not raise
    written = json.loads((tmp_path / "schema.json").read_text(encoding="utf-8"))
    assert "customers" in written


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

def test_round_trip_dataframes_match(
    tmp_path: Path, sample_datasets: dict, sample_schema: dict
) -> None:
    """write_datasets then read_datasets → identical DataFrames."""
    conn = LocalFSConnector(path=tmp_path)
    conn.write_datasets(sample_datasets, schema_metadata=sample_schema)
    read_back = conn.read_datasets(names=list(sample_datasets))
    for name, original_df in sample_datasets.items():
        assert read_back[name].to_dict(as_series=False) == original_df.to_dict(as_series=False)


def test_round_trip_schema_survives_write_read(
    tmp_path: Path, sample_datasets: dict, sample_schema: dict
) -> None:
    conn = LocalFSConnector(path=tmp_path)
    conn.write_datasets(sample_datasets, schema_metadata=sample_schema)
    meta = conn.read_schema_metadata()
    assert meta == sample_schema


# ---------------------------------------------------------------------------
# Integration — through load()
# ---------------------------------------------------------------------------

def test_integration_local_to_local_via_load(
    source_dir: Path, tmp_path: Path, sample_datasets: dict
) -> None:
    """Full load() pipeline: local_fs source → local_fs target."""
    from eds_loader import load
    from eds_loader.config import LoaderConfig

    target_dir = tmp_path / "target"
    config = LoaderConfig(
        source={"kind": "local_fs", "path": str(source_dir)},
        target={"kind": "local_fs", "path": str(target_dir)},
    )
    result = load(config)

    expected_rows = sum(df.height for df in sample_datasets.values())
    assert result.total_rows == expected_rows
    assert set(result.tables_written) == set(sample_datasets)
    for name in sample_datasets:
        assert (target_dir / f"{name}.parquet").is_file()


def test_integration_table_subset_via_load(
    source_dir: Path, tmp_path: Path
) -> None:
    """load() with tables=[...] only loads the selected datasets."""
    from eds_loader import load
    from eds_loader.config import LoaderConfig

    target_dir = tmp_path / "target_subset"
    config = LoaderConfig(
        source={"kind": "local_fs", "path": str(source_dir)},
        target={"kind": "local_fs", "path": str(target_dir)},
        tables=["customers"],
    )
    result = load(config)

    assert result.tables_written == ["customers"]
    assert (target_dir / "customers.parquet").is_file()
    assert not (target_dir / "orders.parquet").exists()


def test_integration_schema_json_written_at_target(
    source_dir: Path, tmp_path: Path
) -> None:
    """The target directory gets schema.json when enforce_constraints=True."""
    from eds_loader import load
    from eds_loader.config import LoaderConfig

    target_dir = tmp_path / "target_schema"
    config = LoaderConfig(
        source={"kind": "local_fs", "path": str(source_dir)},
        target={"kind": "local_fs", "path": str(target_dir)},
    )
    load(config)
    assert (target_dir / "schema.json").is_file()


def test_integration_schema_json_not_written_when_enforce_false(
    source_dir: Path, tmp_path: Path
) -> None:
    """When enforce_constraints=False, target gets no schema.json."""
    from eds_loader import load
    from eds_loader.config import LoaderConfig

    target_dir = tmp_path / "target_no_schema"
    config = LoaderConfig(
        source={"kind": "local_fs", "path": str(source_dir)},
        target={"kind": "local_fs", "path": str(target_dir)},
        enforce_constraints=False,
    )
    load(config)
    assert not (target_dir / "schema.json").exists()
