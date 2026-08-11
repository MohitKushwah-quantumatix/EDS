"""Tests for the eds-loader CLI (validate / init / run / run --dry-run / connectors).

All tests use Typer's ``CliRunner`` — no real I/O, no real connectors.
"""

from __future__ import annotations

import json
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl
import pytest
from typer.testing import CliRunner

from eds_loader.cli.main import app
from eds_loader.cli._templates import SOURCE_TEMPLATES, TARGET_TEMPLATES, build_config
from eds_loader.connectors.base import WriteResult
from eds_loader.loader import LoadResult
from eds_loader.exceptions import ConfigError, LoadError

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path: Path, content: str, name: str = "loader.yaml") -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _sample_schema() -> dict:
    return {
        "customers": {"primary_key": "id", "unique_columns": [], "foreign_keys": []},
        "orders":    {"primary_key": "id", "unique_columns": [], "foreign_keys": []},
    }


def _sample_datasets() -> dict[str, pl.DataFrame]:
    return {
        "customers": pl.DataFrame({"id": [1, 2, 3]}),
        "orders":    pl.DataFrame({"id": [10, 11]}),
    }


def _parquet_bytes(df: pl.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.write_parquet(buf)
    return buf.getvalue()


def _make_local_yaml(tmp_path: Path) -> tuple[Path, Path]:
    """Return (config_path, source_dir) with real Parquet + schema.json."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    datasets = _sample_datasets()
    for name, df in datasets.items():
        df.write_parquet(source_dir / f"{name}.parquet")
    (source_dir / "schema.json").write_text(
        json.dumps(_sample_schema()), encoding="utf-8"
    )
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    cfg = _write_yaml(
        tmp_path,
        f"source:\n  kind: local_fs\n  path: {source_dir}\n"
        f"target:\n  kind: local_fs\n  path: {target_dir}\n",
    )
    return cfg, source_dir


# ---------------------------------------------------------------------------
# --version
# ---------------------------------------------------------------------------

def test_version_flag_shows_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "eds-loader" in result.output


# ---------------------------------------------------------------------------
# connectors
# ---------------------------------------------------------------------------

def test_connectors_command_shows_database_section() -> None:
    result = runner.invoke(app, ["connectors"])
    assert result.exit_code == 0
    assert "DATABASE" in result.output


def test_connectors_command_shows_storage_section() -> None:
    result = runner.invoke(app, ["connectors"])
    assert "STORAGE" in result.output


def test_connectors_command_shows_local_fs_ok() -> None:
    result = runner.invoke(app, ["connectors"])
    assert "[OK]" in result.output
    assert "local_fs" in result.output


# ---------------------------------------------------------------------------
# run — valid local_fs → local_fs
# ---------------------------------------------------------------------------

def test_run_exits_zero_on_success(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    result = runner.invoke(app, ["run", "-c", str(cfg)])
    assert result.exit_code == 0


def test_run_prints_table_with_rows(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    result = runner.invoke(app, ["run", "-c", str(cfg)])
    assert "customers" in result.output
    assert "orders" in result.output
    assert "Done" in result.output


def test_run_prints_timing_in_seconds(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    result = runner.invoke(app, ["run", "-c", str(cfg)])
    assert " s." in result.output


def test_run_table_has_location_column(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    result = runner.invoke(app, ["run", "-c", str(cfg)])
    assert "Location" in result.output


# ---------------------------------------------------------------------------
# run — error paths
# ---------------------------------------------------------------------------

def test_run_missing_config_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "-c", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 2


def test_run_invalid_yaml_exits_2(tmp_path: Path) -> None:
    cfg = _write_yaml(tmp_path, "source: [unclosed")
    result = runner.invoke(app, ["run", "-c", str(cfg)])
    assert result.exit_code == 2


def test_run_unknown_connector_kind_exits_2(tmp_path: Path) -> None:
    cfg = _write_yaml(
        tmp_path,
        "source:\n  kind: nosuchdb\ntarget:\n  kind: local_fs\n  path: /tmp\n",
    )
    result = runner.invoke(app, ["run", "-c", str(cfg)])
    assert result.exit_code == 2


def test_run_load_error_exits_3(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    with patch("eds_loader.cli.main.load", side_effect=LoadError("disk full")):
        result = runner.invoke(app, ["run", "-c", str(cfg)])
    assert result.exit_code == 3
    assert "disk full" in result.output


# ---------------------------------------------------------------------------
# run --dry-run
# ---------------------------------------------------------------------------

def test_dry_run_exits_zero(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    result = runner.invoke(app, ["run", "-c", str(cfg), "--dry-run"])
    assert result.exit_code == 0


def test_dry_run_shows_dataset_names(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    result = runner.invoke(app, ["run", "-c", str(cfg), "--dry-run"])
    assert "customers" in result.output
    assert "orders" in result.output


def test_dry_run_shows_total_rows(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    result = runner.invoke(app, ["run", "-c", str(cfg), "--dry-run"])
    assert "Total" in result.output
    assert "5" in result.output   # 3 customers + 2 orders


def test_dry_run_does_not_write_target(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    target_dir = tmp_path / "target"
    runner.invoke(app, ["run", "-c", str(cfg), "--dry-run"])
    # No parquet files should appear in target
    parquet_files = list(target_dir.glob("*.parquet"))
    assert parquet_files == []


def test_dry_run_shows_dry_run_header(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    result = runner.invoke(app, ["run", "-c", str(cfg), "--dry-run"])
    assert "DRY RUN" in result.output


def test_dry_run_source_error_exits_3(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    with patch(
        "eds_loader.cli.main.get_connector",
        side_effect=LoadError("source down"),
    ):
        result = runner.invoke(app, ["run", "-c", str(cfg), "--dry-run"])
    assert result.exit_code == 3


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def test_validate_good_config_exits_zero(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    result = runner.invoke(app, ["validate", "-c", str(cfg)])
    assert result.exit_code == 0


def test_validate_prints_checkmarks(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    result = runner.invoke(app, ["validate", "-c", str(cfg)])
    assert "✓" in result.output


def test_validate_shows_dataset_count(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    result = runner.invoke(app, ["validate", "-c", str(cfg)])
    assert "2 dataset" in result.output


def test_validate_missing_config_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", "-c", str(tmp_path / "none.yaml")])
    assert result.exit_code == 2


def test_validate_bad_yaml_exits_2(tmp_path: Path) -> None:
    cfg = _write_yaml(tmp_path, ": bad yaml [")
    result = runner.invoke(app, ["validate", "-c", str(cfg)])
    assert result.exit_code == 2


def test_validate_unknown_source_kind_exits_2(tmp_path: Path) -> None:
    cfg = _write_yaml(
        tmp_path,
        "source:\n  kind: nosuch\ntarget:\n  kind: local_fs\n  path: /tmp\n",
    )
    result = runner.invoke(app, ["validate", "-c", str(cfg)])
    assert result.exit_code == 2


def test_validate_source_connectivity_error_exits_3(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    with patch(
        "eds_loader.cli.main.get_connector",
        side_effect=LoadError("connection refused"),
    ):
        result = runner.invoke(app, ["validate", "-c", str(cfg)])
    assert result.exit_code == 3


def test_validate_shows_connector_kinds(tmp_path: Path) -> None:
    cfg, _ = _make_local_yaml(tmp_path)
    result = runner.invoke(app, ["validate", "-c", str(cfg)])
    assert "local_fs" in result.output


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def test_init_generates_file(tmp_path: Path) -> None:
    out = tmp_path / "loader.yaml"
    result = runner.invoke(
        app,
        ["init", "--source", "local_fs", "--target", "postgres", "--output", str(out)],
    )
    assert result.exit_code == 0
    assert out.exists()


def test_init_file_contains_source_kind(tmp_path: Path) -> None:
    out = tmp_path / "cfg.yaml"
    runner.invoke(
        app,
        ["init", "-s", "s3", "-t", "mysql", "-o", str(out)],
    )
    content = out.read_text()
    assert "kind: s3" in content
    assert "kind: mysql" in content


def test_init_file_contains_comments(tmp_path: Path) -> None:
    out = tmp_path / "cfg.yaml"
    runner.invoke(app, ["init", "-s", "local_fs", "-t", "postgres", "-o", str(out)])
    content = out.read_text()
    assert "#" in content   # at least one comment line


def test_init_file_contains_footer(tmp_path: Path) -> None:
    out = tmp_path / "cfg.yaml"
    runner.invoke(app, ["init", "-s", "local_fs", "-t", "postgres", "-o", str(out)])
    content = out.read_text()
    assert "enforce_constraints" in content


def test_init_existing_file_without_force_exits_2(tmp_path: Path) -> None:
    out = tmp_path / "loader.yaml"
    out.write_text("existing", encoding="utf-8")
    result = runner.invoke(
        app, ["init", "-s", "local_fs", "-t", "postgres", "-o", str(out)]
    )
    assert result.exit_code == 2
    assert out.read_text() == "existing"  # not overwritten


def test_init_existing_file_with_force_overwrites(tmp_path: Path) -> None:
    out = tmp_path / "loader.yaml"
    out.write_text("old", encoding="utf-8")
    result = runner.invoke(
        app, ["init", "-s", "local_fs", "-t", "postgres", "-o", str(out), "--force"]
    )
    assert result.exit_code == 0
    assert out.read_text() != "old"


def test_init_unknown_source_exits_2(tmp_path: Path) -> None:
    out = tmp_path / "x.yaml"
    result = runner.invoke(
        app, ["init", "-s", "nosuchsrc", "-t", "postgres", "-o", str(out)]
    )
    assert result.exit_code == 2


def test_init_unknown_target_exits_2(tmp_path: Path) -> None:
    out = tmp_path / "x.yaml"
    result = runner.invoke(
        app, ["init", "-s", "local_fs", "-t", "nosuchdest", "-o", str(out)]
    )
    assert result.exit_code == 2


def test_init_all_source_kinds_produce_files(tmp_path: Path) -> None:
    for kind in SOURCE_TEMPLATES:
        out = tmp_path / f"{kind}.yaml"
        result = runner.invoke(
            app, ["init", "-s", kind, "-t", "local_fs", "-o", str(out)]
        )
        assert result.exit_code == 0, f"init failed for source={kind!r}: {result.output}"
        assert out.exists()


def test_init_all_target_kinds_produce_files(tmp_path: Path) -> None:
    for kind in TARGET_TEMPLATES:
        out = tmp_path / f"tgt_{kind}.yaml"
        result = runner.invoke(
            app, ["init", "-s", "local_fs", "-t", kind, "-o", str(out)]
        )
        assert result.exit_code == 0, f"init failed for target={kind!r}: {result.output}"
        assert out.exists()


def test_init_prints_next_steps(tmp_path: Path) -> None:
    out = tmp_path / "loader.yaml"
    result = runner.invoke(
        app, ["init", "-s", "local_fs", "-t", "postgres", "-o", str(out)]
    )
    assert "validate" in result.output
    assert "run" in result.output


# ---------------------------------------------------------------------------
# _templates module
# ---------------------------------------------------------------------------

def test_build_config_contains_both_kinds() -> None:
    text = build_config("s3", "postgres")
    assert "kind: s3" in text
    assert "kind: postgres" in text


def test_build_config_contains_header_comment() -> None:
    text = build_config("local_fs", "mysql")
    assert "eds-loader init" in text


def test_build_config_unknown_source_raises() -> None:
    with pytest.raises(ValueError, match="Unknown source kind"):
        build_config("nosuch", "postgres")


def test_build_config_unknown_target_raises() -> None:
    with pytest.raises(ValueError, match="Unknown target kind"):
        build_config("local_fs", "nosuch")


# ---------------------------------------------------------------------------
# _print_run_table (unit test — no CLI runner needed)
# ---------------------------------------------------------------------------

def test_print_run_table_includes_location() -> None:
    from eds_loader.cli.main import _print_run_table
    results = [
        WriteResult(dataset="customers", location="s3://bkt/customers.parquet", rows=100),
        WriteResult(dataset="orders",    location="s3://bkt/orders.parquet",    rows=50),
    ]
    lines: list[str] = []
    with patch("typer.echo", side_effect=lambda s, **kw: lines.append(str(s))):
        _print_run_table(results)
    combined = "\n".join(lines)
    assert "customers" in combined
    assert "s3://bkt/customers.parquet" in combined
    assert "100" in combined


def test_print_run_table_empty_does_not_crash() -> None:
    from eds_loader.cli.main import _print_run_table
    _print_run_table([])   # should not raise
