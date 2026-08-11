# EDS Loader

Move EDS-generated Parquet datasets from **any source** to **any target**, driven entirely by a YAML config file. No dependency on `eds_core`.

```bash
pip install eds-loader[postgres]   # core + Postgres driver
eds-loader run --config loader.yaml
```

---

## Installation

```bash
# Core only — local filesystem connector always included:
pip install eds-loader

# Add the connector(s) you need:
pip install eds-loader[postgres]      # PostgreSQL
pip install eds-loader[mysql]         # MySQL
pip install eds-loader[mongodb]       # MongoDB
pip install eds-loader[remote_fs]     # SSH / SFTP
pip install eds-loader[s3]            # AWS S3
pip install eds-loader[azure]         # Azure Blob Storage
pip install eds-loader[gcs]           # Google Cloud Storage

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

| Kind | Role | Extra | Driver |
|---|---|---|---|
| `local_fs` | source / target | *(built-in)* | — |
| `remote_fs` | source / target | `remote_fs` | `paramiko` |
| `s3` | source / target | `s3` | `boto3` |
| `azure_blob` | source / target | `azure` | `azure-storage-blob` |
| `gcs` | source / target | `gcs` | `google-cloud-storage` |
| `postgres` | target | `postgres` | `psycopg` v3 |
| `mysql` | target | `mysql` | `pymysql` |
| `mongodb` | target | `mongodb` | `pymongo` |

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
  path: ./output      # required — directory containing .parquet + schema.json
```

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

### `mongodb` (target only)

```yaml
target:
  kind: mongodb
  host: localhost
  database: eds_db
  username: eds_loader  # optional — omit for unauthenticated
  password_env: EDS_MONGO_PASSWORD
  port: 27017           # optional, default: 27017
  auth_source: admin    # optional — authentication database
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

---

## Related

- `eds_core` (the EDS generator) lives at `../EDS/` in this repo.
- The EDS schema exported by `eds_core.export_schema()` is what `eds_loader` consumes as `schema.json`.
