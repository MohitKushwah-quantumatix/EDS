# EDS Loader

Standalone tool to move EDS-generated Parquet data from any source to any target,
entirely driven by configuration. No dependency on `eds_core`.

## Installation

```bash
# Core loader only (local filesystem connector):
pip install -e "."

# With a specific database driver:
pip install -e ".[postgres]"
pip install -e ".[mongodb]"

# With a cloud storage driver:
pip install -e ".[s3]"
pip install -e ".[azure_blob]"
pip install -e ".[gcs]"

# Everything at once:
pip install -e ".[all]"

# Development tooling:
pip install -e ".[dev]"
```

## Usage

```bash
# Check which connectors are installed:
eds-loader connectors

# Run a load:
eds-loader run --config loader.yaml

# Show version:
eds-loader --version
```

## Example config

```yaml
source:
  kind: local_fs
  path: ./output          # directory containing Parquet files + schema.json

target:
  kind: postgres
  host: localhost
  port: 5432
  database: eds_db
  user: postgres
  password_env: EDS_PG_PASSWORD   # reads os.environ["EDS_PG_PASSWORD"]

tables: []                # empty = load everything from schema.json
enforce_constraints: true
```

## Python library usage

```python
from eds_loader import load
from eds_loader.config import LoaderConfig
from pathlib import Path

config = LoaderConfig.from_yaml(Path("loader.yaml"))
result = load(config)
print(f"{result.total_rows:,} rows written across {len(result.tables_written)} tables")
```

## Development

```bash
pytest tests/ -v
ruff check .
mypy eds_loader
```

## Related

- `eds_core` (the generator) lives at `../EDS/` in this repo.
- See the requirements document for the full build order (Steps 1–9).
