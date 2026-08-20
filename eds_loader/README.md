# EDS Loader

Move EDS-generated Parquet datasets from **any source** to **any target**, driven entirely by a YAML config file. No dependency on `eds_core`.

```bash
pip install eds-loader[postgres]   # core + Postgres driver
eds-loader run --config loader.yaml
```

> **Current version:** `0.1.0` · **Python ≥ 3.12** · **Status:** Beta

---

## Installation

```bash
# Core only — local filesystem connector always included:
pip install eds-loader

# Add the connector(s) you need:
pip install eds-loader[postgres]      # PostgreSQL (psycopg v3)
pip install eds-loader[mysql]         # MySQL (pymysql)
pip install eds-loader[mssql]         # Microsoft SQL Server (pyodbc + ODBC driver)
pip install eds-loader[oracle]        # Oracle Database (oracledb)
pip install eds-loader[mongodb]       # MongoDB (pymongo)
pip install eds-loader[remote_fs]     # SSH / SFTP (paramiko)
pip install eds-loader[s3]            # AWS S3 (boto3)
pip install eds-loader[azure]         # Azure Blob Storage (azure-storage-blob)
pip install eds-loader[gcs]           # Google Cloud Storage (google-cloud-storage)
pip install eds-loader[excel]         # Excel source format (openpyxl)

# Everything at once:
pip install eds-loader[all]

# For development (all drivers + test tooling):
pip install eds-loader[dev]
```

Requires **Python ≥ 3.12**.

---

## Quick Start

```bash
# 1. See which connectors are installed:
eds-loader connectors

# 2. Generate a documented starter config:
eds-loader init --source s3 --target postgres --output loader.yaml

# 3. Fill in the required fields, then validate:
eds-loader validate --config loader.yaml

# 4. Run the load:
eds-loader run --config loader.yaml
```

---

## Connector Matrix

| Kind | Role | Extra | Driver / Notes |
|---|---|---|---|
| `local_fs` | source / target | *(built-in)* | — |
| `remote_fs` | source / target | `remote_fs` | `paramiko` |
| `s3` | source / target | `s3` | `boto3` |
| `azure_blob` | source / target | `azure` | `azure-storage-blob` |
| `gcs` | source / target | `gcs` | `google-cloud-storage` |
| `postgres` | target | `postgres` | `psycopg` v3 |
| `mysql` | target | `mysql` | `pymysql` |
| `mssql` | target | `mssql` | `pyodbc` + OS ODBC driver |
| `oracle` | target | `oracle` | `oracledb` |
| `mongodb` | target | `mongodb` | `pymongo` |

> **Supported source formats:** `parquet` (default), `csv`, `json`, `ndjson`, `excel`, `avro`, `orc`.
> Set the `format:` field under any storage source connector to change the format.

---

## CLI Reference

### `eds-loader run`

```
eds-loader run --config <file> [--dry-run]
```

Reads datasets from the source and writes them to the target.

| Flag | Description |
|---|---|
| `--config`, `-c` | Path to the loader YAML config file *(required)* |
| `--dry-run` | Read from source, preview shapes/rows, exit without writing |

**Exit codes:** `0` success · `2` config error · `3` load failure

---

### `eds-loader validate`

```
eds-loader validate --config <file>
```

Validates the config file without running a full load:
1. Parses the YAML
2. Confirms source and target connector drivers are installed
3. Reads `schema.json` from the source (lightweight connectivity probe)

---

### `eds-loader init`

```
eds-loader init [--source <kind>] [--target <kind>] [--output loader.yaml] [--force]
```

Generates a documented starter YAML config. Every field is present and annotated with a comment explaining its purpose.

| Flag | Default | Description |
|---|---|---|
| `--source`, `-s` | `local_fs` | Source connector kind |
| `--target`, `-t` | `postgres` | Target connector kind |
| `--output`, `-o` | `loader.yaml` | Path to write the config |
| `--force`, `-f` | *(off)* | Overwrite existing file |

---

### `eds-loader connectors`

Lists all registered connectors with install status and pip hints:

```
DATABASE
  [OK] mongodb        (target       )
  [OK] mysql          (target       )
  [OK] postgres       (target       )

STORAGE
  [--] azure_blob     (source/target)  ->  pip install eds-loader[azure]
  [--] gcs            (source/target)  ->  pip install eds-loader[gcs]
  [OK] local_fs       (source/target)
  [OK] remote_fs      (source/target)
  [OK] s3             (source/target)

Install everything at once:  pip install eds-loader[all]
```

---

## Config File Reference

```yaml
# ── Source ──────────────────────────────────────────────────────────────────
source:
  kind: local_fs        # connector kind — see connector matrix above
  path: ./output        # connector-specific fields follow
  # format: parquet     # optional — parquet (default) | csv | json | ndjson | excel | avro | orc

# ── Target ──────────────────────────────────────────────────────────────────
target:
  kind: postgres
  host: localhost
  database: eds_db
  user: eds_loader
  password_env: EDS_PG_PASSWORD   # reads os.environ["EDS_PG_PASSWORD"]
  port: 5432            # optional
  schema: public        # optional

# ── Loader options ───────────────────────────────────────────────────────────
tables: []              # empty = load every dataset from schema.json
                        # subset: [customers, orders, products]
enforce_constraints: true  # false = skip PK/FK/UNIQUE enforcement
schema_required: true   # false = skip schema.json; auto-discover *.parquet files
```

### Credential conventions

| Style | Example | Notes |
|---|---|---|
| Inline | `password: "secret"` | Convenient locally; **never commit** |
| Env-var | `password_env: MY_PASS` | Reads `os.environ["MY_PASS"]` at runtime; safe to commit |

---

## Connector Config Reference

### `local_fs`

```yaml
source:               # or target:
  kind: local_fs
  path: ./output      # required — directory containing dataset files + schema.json
  # format: parquet   # optional — parquet (default) | csv | json | ndjson | excel | avro | orc
```

> **Excel multi-sheet files:** each worksheet becomes a separate dataset named `<stem>_<SheetName>`.

---

### `remote_fs` (SSH / SFTP)

```yaml
source:
  kind: remote_fs
  host: sftp.example.com   # required
  username: eds_user        # required
  remote_path: /data/eds    # required
  port: 22                  # optional, default: 22
  password_env: SFTP_PASS   # preferred over inline password
  key_filename: ~/.ssh/id_rsa  # optional — private key path
```

---

### `s3` (AWS S3)

```yaml
source:
  kind: s3
  bucket: my-eds-bucket    # required
  prefix: datasets/2024/   # optional — scopes files within the bucket
  aws_access_key_id: AKIA…      # optional — omit for AWS credential chain
  aws_secret_access_key_env: AWS_SECRET_ACCESS_KEY
  region: us-east-1             # optional, default: us-east-1
  endpoint_url:                 # optional — MinIO / LocalStack
```

---

### `azure_blob` (Azure Blob Storage)

```yaml
source:
  kind: azure_blob
  account_name: myaccount  # required
  container: eds-data       # required
  prefix: datasets/2024/    # optional
  account_key_env: AZURE_STORAGE_KEY
  # connection_string_env: AZURE_STORAGE_CONN_STR  # alternative
```

---

### `gcs` (Google Cloud Storage)

```yaml
source:
  kind: gcs
  bucket: my-eds-bucket    # required
  prefix: datasets/2024/   # optional
  credentials_env: GOOGLE_APPLICATION_CREDENTIALS  # path to service account JSON
  # credentials_file: /path/to/sa.json              # explicit path
  # project: my-gcp-project                         # GCP project ID
```

---

### `postgres` (target only)

```yaml
target:
  kind: postgres
  host: localhost      # required
  database: eds_db     # required
  user: eds_loader     # required
  password_env: EDS_PG_PASSWORD
  port: 5432           # optional, default: 5432
  schema: public       # optional, default: public
```

---

### `mysql` (target only)

```yaml
target:
  kind: mysql
  host: localhost
  database: eds_db
  user: eds_loader
  password_env: EDS_MYSQL_PASSWORD
  port: 3306           # optional, default: 3306
```

---

### `mssql` (target only)

```yaml
target:
  kind: mssql
  host: localhost
  database: eds_db
  user: eds_loader
  password_env: EDS_MSSQL_PASSWORD
  port: 1433                              # optional, default: 1433
  schema: dbo                             # optional, default: dbo
  driver: "ODBC Driver 17 for SQL Server" # optional — must match an installed ODBC driver
  encrypt: true                           # optional, default: true
  trust_server_certificate: false         # optional, default: false (set true for dev/self-signed)
  connect_timeout: 10                     # optional, default: 10 seconds
```

> **ODBC driver required:** install separately from Microsoft (e.g. `ODBC Driver 17 for SQL Server`).
> List installed drivers with: `python -c "import pyodbc; print(pyodbc.drivers())"`

---

### `mongodb` (target only)

```yaml
target:
  kind: mongodb
  host: localhost
  database: eds_db
  username: eds_loader  # optional — omit for unauthenticated
  password_env: EDS_MONGO_PASSWORD
  port: 27017           # optional, default: 27017
  auth_source: admin    # optional — authentication database, default: admin
  connect_timeout: 10000  # optional, default: 10000 ms (server-selection timeout)
```

---

## Python API

```python
from pathlib import Path
from eds_loader import load
from eds_loader.config import LoaderConfig

config = LoaderConfig.from_yaml(Path("loader.yaml"))
result = load(config)

print(f"Done: {result.total_rows:,} rows across {len(result.tables_written)} tables")
for table, rows in result.rows_written.items():
    print(f"  {table}: {rows:,} rows")
```

### `LoaderConfig` fields

| Field | Type | Default | Description |
|---|---|---|---|
| `source` | `ConnectorConfig` | — | Source connector config |
| `target` | `ConnectorConfig` | — | Target connector config |
| `tables` | `list[str]` | `[]` | Subset of tables to load (empty = all) |
| `enforce_constraints` | `bool` | `True` | Apply PK/FK/UNIQUE on the target |
| `schema_required` | `bool` | `True` | When `False`, skip `schema.json` and auto-discover datasets from `*.parquet` files |

### `LoadResult` fields

| Field | Type | Description |
|---|---|---|
| `tables_written` | `list[str]` | Dataset names written, in write order |
| `rows_written` | `dict[str, int]` | Dataset name → row count |
| `total_rows` | `int` (property) | Sum of all `rows_written` values |
| `write_results` | `list[WriteResult]` | Per-table result objects with `location` |

### Exception hierarchy

```
eds_loader.exceptions.EDSLoaderError
├── ConfigError               # bad config, unknown kind, missing table
├── LoadError                 # I/O failure during read / write
├── ConnectorNotFoundError    # kind not registered
└── ConnectorNotInstalledError  # driver package missing
```

---

## Development

```bash
git clone <repo>
cd eds_loader
pip install -e ".[dev]"

pytest tests/ -v          # run all tests
ruff check .              # lint
mypy eds_loader           # type-check

python -m build --wheel   # build distribution wheel
```

### Running tests by connector area

```bash
pytest tests/test_loader.py      # core loader
pytest tests/test_cli.py         # CLI commands
pytest tests/test_config.py      # config validation
pytest tests/test_mongodb.py     # MongoDB connector
pytest tests/test_postgres.py    # PostgreSQL connector
pytest tests/test_sql_base.py    # shared SQL base (covers mssql behaviour too)
pytest tests/test_local_fs.py    # local filesystem connector
pytest tests/test_remote_fs.py   # SSH/SFTP connector
pytest tests/test_cloud_base.py  # shared cloud base
pytest tests/test_s3.py          # S3 connector
pytest tests/test_azure_blob.py  # Azure Blob connector
pytest tests/test_gcs.py         # GCS connector
```

---

## Related

- `eds_core` (the EDS generator) lives at `../EDS/` in this repo.
- The EDS schema exported by `eds_core.export_schema()` is what `eds_loader` consumes as `schema.json`.
