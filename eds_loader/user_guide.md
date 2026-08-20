# EDS Loader — Complete User Guide

A step-by-step guide from first install to a full production load.

---

## 1. What is `eds_loader`?

`eds_loader` is a standalone Python tool that moves **EDS-generated Parquet datasets**
from any source (local disk, cloud storage, SSH server) to any target
(PostgreSQL, MySQL, MongoDB, cloud storage, local disk).

It is entirely driven by a YAML config file — no code required for the common case.

```
EDS generator
    │
    ▼
 ./output/
   ├── schema.json          ← describes every table's columns + constraints
   ├── customers.parquet
   ├── orders.parquet
   └── products.parquet
    │
    ▼  eds-loader run -c loader.yaml
    │
    ▼
  Target (PostgreSQL / S3 / MongoDB / …)
```

---

## 1.5 Uninstallation 
```bash
pip uninstall eds-loader

```

## 2. Installation

### Minimum install (local filesystem only)
```bash
pip install eds-loader
pip install -e "c:\Users\Mohit Patel\Downloads\EDS\eds_loader[all]"
```

### With a specific connector driver
```bash
# Databases
pip install eds-loader[postgres]      # PostgreSQL (psycopg v3)
pip install eds-loader[mysql]         # MySQL      (pymysql)
pip install eds-loader[mongodb]       # MongoDB    (pymongo)

# Storage
pip install eds-loader[remote_fs]     # SSH / SFTP (paramiko)
pip install eds-loader[s3]            # AWS S3     (boto3)
pip install eds-loader[azure]         # Azure Blob (azure-storage-blob)
pip install eds-loader[gcs]           # GCS        (google-cloud-storage)

# Everything at once
pip install eds-loader[all]
```

> Requires **Python ≥ 3.12**.

---

## 3. Check What's Installed

```bash
eds-loader connectors
```

Output:
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

- `[OK]` — driver is installed, connector is ready.
- `[--]` — driver missing; the hint shows the fix command.
- `(source/target)` — can read AND write datasets.
- `(target)` — write-only (databases don't expose a source interface).

> **All connector kinds:** `local_fs`, `remote_fs`, `s3`, `azure_blob`, `gcs` (storage) · `postgres`, `mysql`, `mssql`, `oracle`, `mongodb` (database targets)

---

## 4. The EDS Output Folder

Every EDS generator run produces a directory like this:

```
./output/
  ├── schema.json         ← always required
  ├── customers.parquet
  ├── orders.parquet
  └── products.parquet
```

**`schema.json`** is the key file. It tells `eds_loader` the table structure,
primary keys, unique columns, and foreign keys so it can create tables and
enforce constraints. Example:

```json
{
  "customers": {
    "primary_key": "customer_id",
    "unique_columns": ["email"],
    "foreign_keys": []
  },
  "orders": {
    "primary_key": "order_id",
    "unique_columns": [],
    "foreign_keys": [
      {
        "column": "customer_id",
        "references": "customers",
        "referenced_column": "customer_id",
        "nullable": false
      }
    ]
  }
}
```

---

## 5. The Config File (`loader.yaml`)

Every run is driven by a YAML file with three top-level sections:

```yaml
source:                   # where to READ data from
  kind: local_fs
  path: ./output
  # format: parquet       # optional — parquet (default) | csv | json | ndjson | excel | avro | orc

target:                   # where to WRITE data to
  kind: postgres
  host: localhost
  database: eds_db
  user: eds_loader
  password_env: EDS_PG_PASSWORD

tables: []                # [] = load every table in schema.json
enforce_constraints: true # apply PK / FK / UNIQUE on the target
schema_required: true     # false = skip schema.json, auto-discover *.parquet files
```

> **`schema_required: false`** — Use when your source directory has no `schema.json` (e.g. a raw
> export from another system). The loader discovers all matching format files automatically and
> loads them without constraint metadata.

### Generate a config automatically

Instead of writing it by hand, use `eds-loader init`:

```bash
# Generate a starter config for any source/target pair:
eds-loader init --source local_fs --target postgres --output loader.yaml

# All available sources: local_fs, remote_fs, s3, azure_blob, gcs
# All available targets: local_fs, remote_fs, s3, azure_blob, gcs,
#                        postgres, mysql, mssql, mongodb
```

The generated file contains every field with comments explaining each one.

---

## 6. Validate Before Running

Always validate before your first run:

```bash
eds-loader validate --config loader.yaml
```

This checks:
1. The YAML parses correctly.
2. Both source and target connector drivers are installed.
3. `schema.json` can be read from the source (lightweight connectivity probe).

Example output:
```
  ✓  Config parsed:  loader.yaml
  ✓  Source connector: local_fs  (installed)
  ✓  Target connector: postgres  (installed)
  ✓  Schema found: 3 dataset(s)  (customers, orders, products)

Config is valid — 3 dataset(s) ready to load.
```

If anything fails it exits with code `2` (config error) or `3` (connectivity
error) with a clear message.

---

## 7. Preview With Dry-Run

See exactly what would be written without touching the target:

```bash
eds-loader run --config loader.yaml --dry-run
```

Output:
```
DRY RUN — no data will be written.

  customers  3 cols, 12,500 rows
  orders     5 cols, 47,200 rows
  products   4 cols,  1,200 rows

Total: 60,900 rows across 3 dataset(s).
Run without --dry-run to write.
```

No data is written. Use this to confirm row counts before a production load.

---

## 8. Run the Load

```bash
eds-loader run --config loader.yaml
```

Output:
```
+-------------+--------+----------------------------------------------+
| Table       |   Rows | Location                                     |
+-------------+--------+----------------------------------------------+
| customers   | 12,500 | postgresql://localhost/eds_db/public/customers|
| orders      | 47,200 | postgresql://localhost/eds_db/public/orders  |
| products    |  1,200 | postgresql://localhost/eds_db/public/products|
+-------------+--------+----------------------------------------------+

Done — 60,900 rows across 3 table(s) in 4.2 s.
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `2` | Config error (bad YAML, unknown connector, missing field) |
| `3` | Runtime error (network failure, auth error, I/O error) |

---

## 9. Connector Config Reference

### 9.1 `local_fs` — Local Directory

Works as **source** and **target** (no extra install needed).

```yaml
source:                   # or target:
  kind: local_fs
  path: ./output          # path to directory with dataset files + schema.json
  # format: parquet       # optional — parquet (default) | csv | json | ndjson | excel | avro | orc
```

**Supported source formats:**

| Format | Extensions | Notes |
|---|---|---|
| `parquet` | `.parquet` | Default — always available |
| `csv` | `.csv` | Plain comma-separated values |
| `json` | `.json` | JSON array of objects |
| `ndjson` | `.ndjson`, `.jsonl` | Newline-delimited JSON |
| `excel` | `.xlsx`, `.xls` | Requires `pip install eds-loader[excel]`; multi-sheet → one dataset per sheet |
| `avro` | `.avro` | Apache Avro |
| `orc` | `.orc` | Apache ORC |

> **Excel multi-sheet behaviour:** a workbook named `sales.xlsx` with sheets `Jan` and `Feb`
> produces datasets named `sales_Jan` and `sales_Feb`. A single-sheet workbook uses the bare
> stem (`sales`).

**Typical use:** quickest way to test a load locally before pushing to a real target.

---

### 9.2 `remote_fs` — SSH / SFTP

Works as **source** and **target**. Install: `pip install eds-loader[remote_fs]`

```yaml
source:
  kind: remote_fs
  host: sftp.example.com       # required
  username: eds_user            # required
  remote_path: /data/eds        # required — remote directory
  port: 22                      # optional, default: 22
  password_env: SFTP_PASSWORD   # preferred — env-var with password
  # password: ""                # inline (not recommended for production)
  # key_filename: ~/.ssh/id_rsa # private key path instead of password
```

Set the env-var before running:
```bash
export SFTP_PASSWORD="my-sftp-password"
eds-loader run -c loader.yaml
```

---

### 9.3 `s3` — AWS S3

Works as **source** and **target**. Install: `pip install eds-loader[s3]`

```yaml
source:
  kind: s3
  bucket: my-eds-bucket         # required
  prefix: datasets/2024/        # optional — scopes files within the bucket
  aws_access_key_id: AKIAIOSFODNN7EXAMPLE   # optional
  aws_secret_access_key_env: AWS_SECRET_ACCESS_KEY
  region: us-east-1             # optional, default: us-east-1
  # format: parquet             # optional — parquet (default) | csv | json | ndjson | excel | avro | orc
  # endpoint_url: http://localhost:9000  # for MinIO / LocalStack
```

If you omit `aws_access_key_id`, boto3 uses its standard credential chain
(environment variables, `~/.aws/credentials`, IAM role, etc.).

```bash
export AWS_SECRET_ACCESS_KEY="your-secret-key"
eds-loader run -c loader.yaml
```

**MinIO / LocalStack example:**
```yaml
source:
  kind: s3
  bucket: local-bucket
  endpoint_url: http://localhost:9000
  aws_access_key_id: minioadmin
  aws_secret_access_key: minioadmin
```

---

### 9.4 `azure_blob` — Azure Blob Storage

Works as **source** and **target**. Install: `pip install eds-loader[azure]`

```yaml
source:
  kind: azure_blob
  account_name: myaccount        # required
  container: eds-data            # required
  prefix: datasets/2024/         # optional
  account_key_env: AZURE_STORAGE_KEY     # env-var for account key
  # connection_string_env: AZURE_STORAGE_CONN_STR  # alternative
```

```bash
export AZURE_STORAGE_KEY="your-account-key"
eds-loader run -c loader.yaml
```

---

### 9.5 `gcs` — Google Cloud Storage

Works as **source** and **target**. Install: `pip install eds-loader[gcs]`

```yaml
source:
  kind: gcs
  bucket: my-eds-bucket          # required
  prefix: datasets/2024/         # optional
  credentials_env: GOOGLE_APPLICATION_CREDENTIALS   # path to service account JSON
  # credentials_file: /path/to/sa.json              # explicit path
  # project: my-gcp-project                         # GCP project ID
```

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service_account.json"
eds-loader run -c loader.yaml
```

---

### 9.6 `postgres` — PostgreSQL

**Target only.** Install: `pip install eds-loader[postgres]`

```yaml
target:
  kind: postgres
  host: localhost                # required
  database: eds_db               # required
  user: eds_loader               # required
  password_env: EDS_PG_PASSWORD  # preferred
  # password: ""                 # inline (not recommended)
  port: 5432                     # optional, default: 5432
  schema: public                 # optional, default: public
```

**What it does:**
- Creates tables using DDL derived from `schema.json`.
- Drops and recreates tables on each run (idempotent).
- Writes data in **FK-dependency order** (parent tables before child tables).
- Creates PRIMARY KEY, UNIQUE, and FOREIGN KEY constraints when `enforce_constraints: true`.
- Uses `COPY` for bulk insert (fast).

```bash
export EDS_PG_PASSWORD="my-postgres-password"
eds-loader run -c loader.yaml
```

---

### 9.7 `mysql` — MySQL

**Target only.** Install: `pip install eds-loader[mysql]`

```yaml
target:
  kind: mysql
  host: localhost
  database: eds_db               # required — must already exist
  user: eds_loader
  password_env: EDS_MYSQL_PASSWORD
  port: 3306                     # optional, default: 3306
```

**What it does:** Same as PostgreSQL — DDL, FK-ordered writes, bulk insert,
constraint enforcement. Uses backtick quoting and `FOREIGN_KEY_CHECKS` hooks.

> **Note:** The database must already exist. `eds_loader` creates tables,
> not the database itself.

---

### 9.9 `mssql` — Microsoft SQL Server

**Target only.** Install: `pip install eds-loader[mssql]`

> **ODBC driver required:** An OS-level ODBC driver must be installed separately.
> Download from Microsoft: [ODBC Driver for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server).
> List installed drivers: `python -c "import pyodbc; print(pyodbc.drivers())"`

```yaml
target:
  kind: mssql
  host: localhost               # required — hostname or IP
  database: eds_db              # required
  user: eds_loader              # required — SQL authentication login
  password_env: EDS_MSSQL_PASSWORD  # preferred
  # password: ""               # inline (not recommended for production)
  port: 1433                    # optional, default: 1433
  schema: dbo                   # optional, default: dbo
  driver: "ODBC Driver 17 for SQL Server"  # optional — must match an installed driver
  encrypt: true                 # optional, default: true
  trust_server_certificate: false  # optional, default: false (set true for dev/self-signed certs)
  connect_timeout: 10           # optional, default: 10 seconds
```

**What it does:**
- Creates tables using T-SQL DDL derived from `schema.json`.
- Drops all FK constraints in the target schema before `DROP TABLE` (T-SQL
  does not support per-session FK-check disabling like MySQL).
- Uses `fast_executemany = True` for bulk inserts (pyodbc row-at-a-time is
  dramatically slower without this).
- Promotes `NVARCHAR(MAX)` to `NVARCHAR(255)` on key/index columns (SQL
  Server cannot use `MAX` columns as PK/UNIQUE/FK keys).
- Writes data in **FK-dependency order** (parent tables before child tables).
- Creates PRIMARY KEY, UNIQUE, and FOREIGN KEY constraints when
  `enforce_constraints: true`.

```bash
export EDS_MSSQL_PASSWORD="my-mssql-password"
eds-loader run -c loader.yaml
```

---

### 9.8 `mongodb` — MongoDB

**Target only.** Install: `pip install eds-loader[mongodb]`

```yaml
target:
  kind: mongodb
  host: localhost
  database: eds_db
  # username: eds_loader              # optional
  # password_env: EDS_MONGO_PASSWORD  # optional — omit for unauthenticated
  port: 27017                         # optional, default: 27017
  # auth_source: admin                # optional, default: admin
  # connect_timeout: 10000            # optional, default: 10000 ms (server-selection)
```

**What it does:**
- Drops and recreates each collection on every run.
- Inserts documents using `insert_many` (bulk insert).
- Creates indexes when `enforce_constraints: true`:
  - Primary key column → unique index.
  - Unique columns → unique indexes.
  - Foreign key columns → regular indexes (for query performance).
- **No FK-ordering** — MongoDB collections are independent.

---

## 10. Advanced Scenarios

### Load Only a Subset of Tables

```yaml
source:
  kind: local_fs
  path: ./output

target:
  kind: postgres
  host: localhost
  database: eds_db
  user: eds_loader
  password_env: EDS_PG_PASSWORD

tables:                    # only load these two tables
  - customers
  - orders

enforce_constraints: true
```

---

### Load Without `schema.json` (`schema_required: false`)

Use this when the source directory has no `schema.json` — for example, a raw
export from a non-EDS system or an ad-hoc Parquet dump:

```yaml
source:
  kind: local_fs
  path: ./raw_exports

target:
  kind: mongodb
  host: localhost
  database: eds_db

tables: []
enforce_constraints: false   # no schema.json → no constraint metadata
schema_required: false       # skip schema.json — auto-discover *.parquet files
```

With `schema_required: false`:
- Every `.parquet` file (or other format file) in the source directory is loaded.
- `schema.json` is never read or required.
- Constraint enforcement is automatically disabled (no metadata to forward).
- You can still use `tables: [name1, name2]` to restrict which files are loaded.

---

### Load CSV / Excel / JSON Source Data

Any storage source connector supports a `format:` field. Example — loading
CSV exports into MongoDB:

```yaml
source:
  kind: local_fs
  path: ./csv_exports
  format: csv              # read *.csv files instead of *.parquet

target:
  kind: mongodb
  host: localhost
  database: eds_db

schema_required: false     # CSV exports typically have no schema.json
enforce_constraints: false
```

Example — loading an Excel workbook from S3:

```yaml
source:
  kind: s3
  bucket: my-reports-bucket
  prefix: monthly/
  format: excel
  aws_secret_access_key_env: AWS_SECRET_ACCESS_KEY

target:
  kind: postgres
  host: localhost
  database: eds_db
  user: eds_loader
  password_env: EDS_PG_PASSWORD

schema_required: false
enforce_constraints: false
```

> **Excel note:** each sheet becomes a separate dataset. A `sales.xlsx` with
> sheets `Jan` and `Feb` produces tables `sales_Jan` and `sales_Feb`.
> Requires `pip install eds-loader[excel]`.

---

### Skip Constraint Enforcement (Fast Load)

```yaml
source:
  kind: s3
  bucket: my-bucket

target:
  kind: postgres
  host: localhost
  database: eds_db
  user: eds_loader
  password_env: EDS_PG_PASSWORD

enforce_constraints: false   # skip PK/FK/UNIQUE — fastest possible load
```

Useful when you want to quickly populate a dev database without worrying about
constraint ordering.

---

### Cloud Storage → Database (Common Production Pattern)

EDS generator runs on a CI server and uploads to S3.
`eds_loader` pulls from S3 and loads into PostgreSQL:

```yaml
source:
  kind: s3
  bucket: my-eds-outputs
  prefix: runs/2024-08-10/
  aws_secret_access_key_env: AWS_SECRET_ACCESS_KEY

target:
  kind: postgres
  host: prod-db.internal
  database: eds_prod
  user: eds_loader
  password_env: EDS_PG_PASSWORD
  schema: synthetic

tables: []
enforce_constraints: true
```

```bash
export AWS_SECRET_ACCESS_KEY="..."
export EDS_PG_PASSWORD="..."
eds-loader run -c loader.yaml
```

---

### Local → S3 (Archive Parquet to Cloud)

```yaml
source:
  kind: local_fs
  path: ./output

target:
  kind: s3
  bucket: my-archive-bucket
  prefix: eds/2024-08-10/
  aws_secret_access_key_env: AWS_SECRET_ACCESS_KEY
```

This copies every Parquet file + schema.json to S3. The result is usable as a
`source` for a future load.

---

### SSH Server → MongoDB

```yaml
source:
  kind: remote_fs
  host: data-server.example.com
  username: eds_reader
  remote_path: /exports/eds
  password_env: SFTP_PASSWORD

target:
  kind: mongodb
  host: mongo.example.com
  database: eds_db
  username: eds_writer
  password_env: MONGO_PASSWORD
```

---

## 11. Python API

For programmatic use without the CLI:

```python
from pathlib import Path
from eds_loader import load
from eds_loader.config import LoaderConfig

# Load from YAML file
config = LoaderConfig.from_yaml(Path("loader.yaml"))
result = load(config)

print(f"Done: {result.total_rows:,} rows across {len(result.tables_written)} tables")
for table, rows in result.rows_written.items():
    print(f"  {table}: {rows:,} rows")
```

### Build config in code (no YAML file)

```python
from eds_loader import load
from eds_loader.config import LoaderConfig

config = LoaderConfig(
    source={"kind": "local_fs", "path": "./output"},
    target={
        "kind": "postgres",
        "host": "localhost",
        "database": "eds_db",
        "user": "eds_loader",
        "password": "my-password",   # or use password_env in production
    },
    tables=[],            # all tables
    enforce_constraints=True,
)

result = load(config)
```

### LoadResult fields

```python
result.tables_written    # list[str]       — dataset names in write order
result.rows_written      # dict[str, int]  — dataset → row count
result.total_rows        # int             — sum of all rows
result.write_results     # list[WriteResult] — per-table with .location field
```

### Exception handling

```python
from eds_loader.exceptions import (
    ConfigError,               # bad config, unknown connector
    LoadError,                 # I/O failure during read/write
    ConnectorNotFoundError,    # connector kind not registered
    ConnectorNotInstalledError # driver package not installed
)

try:
    result = load(config)
except ConnectorNotInstalledError as exc:
    print(f"Install missing driver: {exc}")
except ConfigError as exc:
    print(f"Fix your config: {exc}")
except LoadError as exc:
    print(f"Load failed: {exc}")
```

---

## 12. Credentials Best Practices

| Method | Config field | How it works | Suitable for |
|---|---|---|---|
| Inline | `password: "secret"` | Value in YAML | Local dev only |
| Env-var | `password_env: MY_VAR` | Reads `os.environ["MY_VAR"]` | CI / production |

**Never commit inline credentials to version control.**

Always use the `_env` form in production:

```yaml
target:
  kind: postgres
  password_env: EDS_PG_PASSWORD   # safe — YAML has no secret value
```

```bash
# Set in your CI/CD pipeline, Docker env, or shell:
export EDS_PG_PASSWORD="actual-secret-here"
eds-loader run -c loader.yaml
```

---

## 13. Complete Workflow — End to End

```bash
# Step 1: Install eds-loader with the drivers you need
pip install eds-loader[postgres,s3]

# Step 2: Check connectors are ready
eds-loader connectors

# Step 3: Generate a starter config
eds-loader init --source s3 --target postgres --output loader.yaml

# Step 4: Edit loader.yaml — fill in bucket name, host, database, etc.
#         Set credential env-vars

# Step 5: Validate the config
eds-loader validate --config loader.yaml

# Step 6: Preview the load (no writes)
eds-loader run --config loader.yaml --dry-run

# Step 7: Run the actual load
eds-loader run --config loader.yaml

# Step 8 (Python): Access the result programmatically if needed
python -c "
from eds_loader import load
from eds_loader.config import LoaderConfig
from pathlib import Path
r = load(LoaderConfig.from_yaml(Path('loader.yaml')))
print(r.total_rows, 'rows written')
"
```

---

## 14. Troubleshooting

### `[--]` in `eds-loader connectors`
```
  [--] postgres  ->  pip install eds-loader[postgres]
```
**Fix:** Run the shown pip command.

---

### `Configuration error: Config file not found`
**Fix:** Check the path you passed to `--config`. Use an absolute path if needed.

---

### `Configuration error: Config validation error`
**Fix:** Run `eds-loader validate -c loader.yaml` — it shows exactly which field
is wrong. Check for missing required fields (`host`, `database`, `bucket`, etc.).

---

### `Load failed: Environment variable 'XYZ' is not set`
**Fix:** Set the environment variable before running:
```bash
export XYZ="your-value"
eds-loader run -c loader.yaml
```

---

### `Load failed: Cannot create S3 client`
**Fix:** Check `aws_access_key_id` and `aws_secret_access_key_env`. If using
the credential chain (no keys in config), ensure `~/.aws/credentials` is set
or the IAM role is attached.

---

### `Load failed: Cannot create Azure Blob client`
**Fix:** Verify `account_name` is correct and the `account_key_env` / 
`connection_string_env` variable is set and valid.

---

### `Configuration error: Table(s) not found in schema.json`
You listed a table in `tables:` that doesn't exist in `schema.json`.
**Fix:** Run `eds-loader validate -c loader.yaml` to see what tables are
actually in the schema, or set `tables: []` to load all.

---

### Postgres: `FOREIGN KEY constraint violation` during DDL
**Fix:** Set `enforce_constraints: true` (default). The loader automatically
writes parent tables before child tables (topological sort). If you see this
error, check that `schema.json` has correct `foreign_keys` entries.

---

### MySQL: `Unknown database 'eds_db'`
**Fix:** The MySQL target requires the database to **already exist**:
```sql
CREATE DATABASE eds_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

---

### MSSQL: `Cannot connect to MSSQL` / driver error
**Fix:** Confirm the ODBC driver named in the `driver:` field is installed:
```bash
python -c "import pyodbc; print(pyodbc.drivers())"
```
Download from Microsoft if missing:
https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server

---

### MSSQL: `Cannot open database requested by the login`
**Fix:** Verify `database` and `host` fields. Also check that the SQL login
has `CONNECT` permission on the target database.

---

### MSSQL: SSL/TLS handshake errors (local/dev server)
**Fix:** Add `trust_server_certificate: true` to the config for self-signed certs.

---

### `Load failed: Unknown format`
You set `format:` to an unsupported value.
**Fix:** Use one of: `parquet`, `csv`, `json`, `ndjson`, `excel`, `avro`, `orc`.

---

### `Load failed: Excel format requires openpyxl`
**Fix:** `pip install eds-loader[excel]`

---

### MongoDB: Documents overwritten on every run
This is by design — `eds_loader` **drops and recreates** each collection on
every run (idempotent behaviour). To preserve existing data, do not use
`eds_loader` as a streaming / incremental loader.

---

## 16. CI/CD Pipeline Integration

The most common production setup: EDS generates data in CI, uploads to S3,
then `eds_loader` pulls from S3 and loads to a database.

### GitHub Actions Example

```yaml
# .github/workflows/eds-load.yml
name: EDS Data Load

on:
  workflow_dispatch:      # manual trigger
  schedule:
    - cron: '0 2 * * *'  # nightly at 2 AM UTC

jobs:
  load:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install eds-loader
        run: pip install eds-loader[postgres,s3]

      - name: Validate config
        run: eds-loader validate -c configs/prod.yaml
        env:
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          EDS_PG_PASSWORD: ${{ secrets.EDS_PG_PASSWORD }}

      - name: Dry run
        run: eds-loader run -c configs/prod.yaml --dry-run
        env:
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          EDS_PG_PASSWORD: ${{ secrets.EDS_PG_PASSWORD }}

      - name: Run load
        run: eds-loader run -c configs/prod.yaml
        env:
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          EDS_PG_PASSWORD: ${{ secrets.EDS_PG_PASSWORD }}
```

Store all secrets in **GitHub → Settings → Secrets and Variables → Actions**.
The YAML file is safe to commit — it contains no actual credentials.

---

### Docker / Docker Compose Example

```dockerfile
# Dockerfile
FROM python:3.12-slim
RUN pip install eds-loader[postgres,s3]
COPY loader.yaml /app/loader.yaml
WORKDIR /app
CMD ["eds-loader", "run", "--config", "loader.yaml"]
```

```yaml
# docker-compose.yml
services:
  eds-loader:
    build: .
    environment:
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY}
      EDS_PG_PASSWORD: ${EDS_PG_PASSWORD}
    depends_on:
      - postgres

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: eds_db
      POSTGRES_USER: eds_loader
      POSTGRES_PASSWORD: ${EDS_PG_PASSWORD}
```

```bash
# Run with .env file:
# .env contains AWS_SECRET_ACCESS_KEY=... and EDS_PG_PASSWORD=...
docker compose --env-file .env up eds-loader
```

---

## 17. Multi-Environment Config Management

Keep one config per environment. Only the connection details change — the
`source` structure and `tables` list stay the same.

```
configs/
  dev.yaml       # local_fs source → local postgres
  staging.yaml   # s3 source → staging postgres
  prod.yaml      # s3 source → prod postgres
```

```yaml
# configs/dev.yaml
source:
  kind: local_fs
  path: ./output
target:
  kind: postgres
  host: localhost
  database: eds_dev
  user: eds_loader
  password: devpassword
enforce_constraints: true
```

```yaml
# configs/staging.yaml
source:
  kind: s3
  bucket: eds-staging-bucket
  aws_secret_access_key_env: AWS_SECRET_ACCESS_KEY
target:
  kind: postgres
  host: staging-db.internal
  database: eds_staging
  user: eds_loader
  password_env: EDS_PG_PASSWORD
enforce_constraints: true
```

```yaml
# configs/prod.yaml
source:
  kind: s3
  bucket: eds-prod-bucket
  prefix: latest/
  aws_secret_access_key_env: AWS_SECRET_ACCESS_KEY
target:
  kind: postgres
  host: prod-db.internal
  database: eds_prod
  user: eds_loader
  password_env: EDS_PG_PASSWORD
  schema: synthetic
enforce_constraints: true
```

Run each with:
```bash
eds-loader run -c configs/dev.yaml
eds-loader run -c configs/staging.yaml
eds-loader run -c configs/prod.yaml
```

---

## 18. Python API — Advanced Patterns

### Pattern 1: Build config programmatically from env-vars

```python
import os
from eds_loader import load
from eds_loader.config import LoaderConfig

ENV = os.environ.get("APP_ENV", "dev")

SOURCES = {
    "dev":     {"kind": "local_fs", "path": "./output"},
    "staging": {"kind": "s3", "bucket": "eds-staging",
                "aws_secret_access_key_env": "AWS_SECRET_ACCESS_KEY"},
    "prod":    {"kind": "s3", "bucket": "eds-prod", "prefix": "latest/",
                "aws_secret_access_key_env": "AWS_SECRET_ACCESS_KEY"},
}

config = LoaderConfig(
    source=SOURCES[ENV],
    target={
        "kind": "postgres",
        "host": os.environ["DB_HOST"],
        "database": os.environ["DB_NAME"],
        "user": os.environ["DB_USER"],
        "password_env": "DB_PASSWORD",
    },
    enforce_constraints=True,
)

result = load(config)
print(f"[{ENV}] {result.total_rows:,} rows loaded")
```

---

### Pattern 2: Multiple sequential loads

```python
from pathlib import Path
from eds_loader import load
from eds_loader.config import LoaderConfig

configs = [
    Path("configs/customers.yaml"),
    Path("configs/orders.yaml"),
    Path("configs/products.yaml"),
]

total = 0
for cfg_path in configs:
    config = LoaderConfig.from_yaml(cfg_path)
    result = load(config)
    total += result.total_rows
    print(f"{cfg_path.stem}: {result.total_rows:,} rows")

print(f"\nGrand total: {total:,} rows")
```

---

### Pattern 3: Read the schema before loading (inspection)

```python
from eds_loader.connectors.registry import get_connector

# Just read schema.json — no load needed
source = get_connector("s3", {
    "bucket": "my-bucket",
    "aws_secret_access_key_env": "AWS_SECRET_ACCESS_KEY",
})

schema = source.read_schema_metadata()
for table, meta in schema.items():
    pk = meta.get("primary_key", "(none)")
    fk_count = len(meta.get("foreign_keys", []))
    print(f"{table:<20}  PK: {pk:<20}  FKs: {fk_count}")
```

---

### Pattern 4: Load with per-result reporting

```python
from eds_loader import load
from eds_loader.config import LoaderConfig
from pathlib import Path

result = load(LoaderConfig.from_yaml(Path("loader.yaml")))

# write_results carries location URLs per table
for r in result.write_results:
    print(f"  {r.dataset:<20} {r.rows:>10,} rows  → {r.location}")
```

---

## 19. Performance Tips

### Tip 1 — `enforce_constraints: false` for large loads

Skipping constraint creation (PKs, FKs, unique indexes) is significantly
faster for very large datasets. Load first, add constraints later if needed:

```yaml
enforce_constraints: false   # skip DDL constraints → ~2-4x faster
```

### Tip 2 — Load a subset first (smoke test)

```yaml
tables:
  - customers    # load just one table to verify the pipeline
```

Once confirmed, change to `tables: []` for the full load.

### Tip 3 — Use the `prefix` field to load specific runs

If S3 / GCS has multiple EDS runs stored under different prefixes, point at
one specific run without moving any files:

```yaml
source:
  kind: s3
  bucket: eds-archive
  prefix: runs/2024-08-10/     # load just this run
```

### Tip 4 — For Postgres, choose the right schema

Putting EDS data in its own schema keeps it isolated:

```yaml
target:
  kind: postgres
  schema: synthetic    # tables go to synthetic.customers, synthetic.orders
```

This avoids name collisions with your application tables in `public`.

### Tip 5 — Use `--dry-run` before any production load

Always confirm row counts before committing:

```bash
eds-loader run -c prod.yaml --dry-run   # check counts
eds-loader run -c prod.yaml             # actually run
```

---

## 20. How to Write a Custom Connector

You can add your own connector by subclassing the appropriate base class
and registering it. No changes to `eds_loader` source are needed.

### Option A — Custom cloud / file storage connector

Subclass `CloudBaseConnector` and override 5 methods:

```python
# my_connectors/my_storage.py
from eds_loader.connectors._cloud_base import CloudBaseConnector
from eds_loader.connectors.registry import ConnectorSpec, register_connector

class MyStorageConnector(CloudBaseConnector):
    def __init__(self, base_url: str, **kwargs):
        super().__init__(**kwargs)
        self._base_url = base_url

    def _connect(self):
        # return your client object
        return MyStorageClient(self._base_url)

    def _list_parquet_keys(self) -> list[str]:
        client = self._get_client()
        return [f for f in client.list(self._prefix) if f.endswith(".parquet")]

    def _read_bytes(self, key: str) -> bytes:
        return self._get_client().download(key)

    def _write_bytes(self, key: str, data: bytes) -> None:
        self._get_client().upload(key, data)

    def _location(self, dataset_name: str) -> str:
        return f"mystorage://{self._base_url}/{self._key(f'{dataset_name}.parquet')}"


# Register it
register_connector(
    "my_storage",
    ConnectorSpec(
        connector_class=MyStorageConnector,
        required_packages=[],   # list any third-party packages needed
        install_extra="my_storage",
        can_read=True,
        can_write=True,
        description="Custom storage connector",
    ),
)
```

### Option B — Custom database (write-only) connector

```python
# my_connectors/my_db.py
from eds_loader.connectors.base import WriteResult
from eds_loader.connectors.registry import ConnectorSpec, register_connector

class MyDBConnector:
    """Write-only connector for MyDB."""

    def __init__(self, host: str, database: str, **kwargs):
        self._host = host
        self._db = database

    def write_datasets(
        self,
        datasets: dict,
        schema_metadata: dict,
    ) -> list[WriteResult]:
        results = []
        for name, df in datasets.items():
            # your write logic here
            rows_written = self._write_table(name, df)
            results.append(WriteResult(
                dataset=name,
                location=f"mydb://{self._host}/{self._db}/{name}",
                rows=rows_written,
            ))
        return results

    def _write_table(self, name: str, df) -> int:
        # implement your actual write
        return df.height


register_connector(
    "my_db",
    ConnectorSpec(
        connector_class=MyDBConnector,
        required_packages=[],
        install_extra="my_db",
        can_read=False,
        can_write=True,
        description="Custom database connector",
    ),
)
```

### Using the custom connector

```python
import my_connectors.my_db  # triggers register_connector()

from eds_loader import load
from eds_loader.config import LoaderConfig

config = LoaderConfig(
    source={"kind": "local_fs", "path": "./output"},
    target={"kind": "my_db", "host": "myhost", "database": "mydb"},
)
result = load(config)
```

Or from the CLI — import your module before invoking:

```python
# run_load.py
import my_connectors.my_db   # register before CLI runs
from eds_loader.cli.main import app
app()
```

```bash
python run_load.py run -c loader.yaml
```

---

## 15. Quick Reference

```bash
# Commands
eds-loader --version
eds-loader connectors
eds-loader init -s <source> -t <target> -o loader.yaml
eds-loader validate -c loader.yaml
eds-loader run -c loader.yaml
eds-loader run -c loader.yaml --dry-run

# Install extras
pip install eds-loader[postgres]
pip install eds-loader[mysql]
pip install eds-loader[mssql]        # + OS ODBC driver from Microsoft
pip install eds-loader[oracle]
pip install eds-loader[mongodb]
pip install eds-loader[remote_fs]
pip install eds-loader[s3]
pip install eds-loader[azure]
pip install eds-loader[gcs]
pip install eds-loader[excel]
pip install eds-loader[all]

# Connector kinds
# Sources:  local_fs, remote_fs, s3, azure_blob, gcs
# Targets:  local_fs, remote_fs, s3, azure_blob, gcs,
#           postgres, mysql, mssql, oracle, mongodb

# Source formats (set via format: field)
# parquet (default) | csv | json | ndjson | excel | avro | orc

# Key config fields
# schema_required: true    # false = skip schema.json, auto-discover files
# enforce_constraints: true
# tables: []               # [] = all tables
```
