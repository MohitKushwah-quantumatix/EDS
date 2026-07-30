"""Tests for the Parquet exporter."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from eds.domain.master_data import MASTER_DATA_DATASETS, dataset_by_name
from eds.exporters.parquet.writer import ExportError, write_dataset, write_datasets
from eds.generators.master_data import MasterData


def test_write_dataset_creates_the_file(tmp_path: Path) -> None:
    """A dataset is written to ``<name>.parquet``."""
    frame = pl.DataFrame({"a": [1, 2, 3]})

    path = write_dataset("sample", frame, tmp_path)

    assert path == tmp_path / "sample.parquet"
    assert path.is_file()


def test_write_dataset_creates_missing_directories(tmp_path: Path) -> None:
    """Nested output directories are created on demand."""
    destination = tmp_path / "deep" / "nested"

    path = write_dataset("sample", pl.DataFrame({"a": [1]}), destination)

    assert path.is_file()


def test_written_data_round_trips(tmp_path: Path) -> None:
    """Reading the file back yields the original frame."""
    frame = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})

    path = write_dataset("sample", frame, tmp_path)

    assert pl.read_parquet(path).equals(frame)


def test_empty_frame_round_trips_with_its_schema(tmp_path: Path) -> None:
    """An empty dataset still records its schema."""
    dataset = dataset_by_name("brands")
    frame = pl.DataFrame(schema=dataset.polars_schema())

    path = write_dataset(dataset.name, frame, tmp_path)
    restored = pl.read_parquet(path)

    assert restored.height == 0
    assert restored.columns == list(dataset.column_names)


def test_write_datasets_writes_every_file(master_data: MasterData, tmp_path: Path) -> None:
    """All thirteen documented outputs are produced."""
    written = write_datasets(master_data.datasets, tmp_path)

    assert set(written) == set(master_data.datasets)
    for dataset in MASTER_DATA_DATASETS:
        assert (tmp_path / dataset.file_name).is_file()


def test_exported_files_preserve_schema_and_row_counts(
    master_data: MasterData, tmp_path: Path
) -> None:
    """Every exported file matches the in-memory frame exactly."""
    write_datasets(master_data.datasets, tmp_path)

    for name, frame in master_data:
        restored = pl.read_parquet(tmp_path / f"{name}.parquet")
        assert restored.height == frame.height, name
        assert restored.schema == frame.schema, name


def test_export_fails_when_the_path_is_a_file(tmp_path: Path) -> None:
    """Writing into a path occupied by a file reports an export error."""
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ExportError):
        write_dataset("sample", pl.DataFrame({"a": [1]}), blocker)
