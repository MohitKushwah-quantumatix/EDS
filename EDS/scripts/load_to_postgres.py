"""Load generated Parquet datasets into PostgreSQL, driven by configs/postgres.yaml.

Usage:

    python scripts/load_to_postgres.py
    python scripts/load_to_postgres.py --output output --config-dir configs

Reads `configs/postgres.yaml` for the connection, schema, constraint, and
table selection (see that file for what each setting does), then writes the
selected datasets from a Parquet output directory into PostgreSQL.

If `tables` in the config is empty, every `.parquet` file found in the
output directory is loaded. If `enforce_constraints` is true, dataset names
that appear in `eds.runners.retail.postgres_schema.RETAIL_DATASET_SCHEMAS`
get real primary key / foreign key / uniqueness constraints; any other name
falls back to a table Polars infers from its own columns.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eds.adapters.parquet.reader import read_dataset
from eds.adapters.postgres.adapter import PostgresAdapter
from eds.adapters.postgres.config import load_postgres_config
from eds.core.config import ConfigError
from eds.runners.retail.postgres_schema import RETAIL_DATASET_SCHEMAS


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("output"), help="Parquet output directory (default: output)"
    )
    parser.add_argument(
        "--config-dir", type=Path, default=None, help="Directory holding postgres.yaml (default: configs/)"
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    try:
        config = load_postgres_config(args.config_dir)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    if config.tables:
        names = list(config.tables)
    else:
        names = sorted(f.stem for f in args.output.glob("*.parquet"))

    if not names:
        print(f"No datasets found in {args.output} and no `tables` were listed in the config.", file=sys.stderr)
        return 1

    print(f"Loading {len(names)} dataset(s) from {args.output} into "
          f"{config.host}:{config.port}/{config.database} (schema={config.schema_name})")

    try:
        frames = {name: read_dataset(name, args.output) for name in names}
    except OSError as exc:
        print(f"Could not read a dataset: {exc}", file=sys.stderr)
        return 1

    dataset_schemas = RETAIL_DATASET_SCHEMAS if config.enforce_constraints else None
    adapter = PostgresAdapter(config.dsn, schema=config.schema_name, dataset_schemas=dataset_schemas)
    try:
        results = adapter.write(frames)
    except Exception as exc:  # noqa: BLE001 - reported to the user, then re-raised as a clean exit
        print(f"Write failed: {exc}", file=sys.stderr)
        return 1
    finally:
        adapter.dispose()

    for result in results:
        print(f"  {result.dataset:<28} -> {result.location:<40} {result.rows:>8,} rows")
    print(f"Done. {sum(r.rows for r in results):,} total rows across {len(results)} table(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
