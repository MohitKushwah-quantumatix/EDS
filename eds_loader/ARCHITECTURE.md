# EDS Loader — Architecture & Full Workflow Reference

> **Purpose:** This document explains exactly how `eds_loader` works — every layer of the code,
> every technology used, and every real-world scenario — so that anyone reading it can fully
> understand the project without needing to read the source code first.

---

## Table of Contents

1. [What is EDS Loader?](#1-what-is-eds-loader)
2. [Technology Stack](#2-technology-stack)
3. [Project Structure](#3-project-structure)
4. [Architecture Overview](#4-architecture-overview)
5. [Core Concepts](#5-core-concepts)
6. [Full Code Flow — Step by Step](#6-full-code-flow--step-by-step)
7. [The Connector System — Deep Dive](#7-the-connector-system--deep-dive)
8. [The Registry System — How Connectors Self-Register](#8-the-registry-system--how-connectors-self-register)
9. [The Format System — Multi-Format Source Support](#9-the-format-system--multi-format-source-support)
10. [SQL Base Layer — Shared Database Logic](#10-sql-base-layer--shared-database-logic)
11. [The Config System](#11-the-config-system)
12. [Logging & Progress System](#12-logging--progress-system)
13. [Exception Hierarchy](#13-exception-hierarchy)
14. [Incremental Load — State & Upsert](#14-incremental-load--state--upsert) *(v0.3+)*
15. [Data Quality — Validation & Schema Drift](#15-data-quality--validation--schema-drift) *(v0.4+)*
16. [Observability — Metrics, History & Notifications](#16-observability--metrics-history--notifications) *(v0.4+)*
17. [All Real-World Scenarios](#17-all-real-world-scenarios)
18. [Data Flow Diagrams](#18-data-flow-diagrams)
19. [Security — Credential Handling](#19-security--credential-handling)
20. [How to Add a New Connector](#20-how-to-add-a-new-connector)

---

## 1. What is EDS Loader?

`eds_loader` is a **config-driven data pipeline tool** that moves datasets from
any source location to any target location. It is the second half of the EDS
(Enterprise Data Simulator) system:

```
+------------------+        generates        +------------------------+
|   eds_core       | ----------------------> |   ./output/            |
|  (EDS Generator) |                         |   |- schema.json       |
+------------------+                         |   |- customers.csv     |
                                             |   |- orders.parquet    |
                                             +------------+-----------+
                                                          |
                                         eds-loader run -c loader.yaml
                                                          |
                                                          v
                                             +------------------------+
                                             |   Target               |
                                             |  PostgreSQL / MongoDB  |
                                             |  / S3 / Azure / ...   |
                                             +------------------------+
```

**Key design principles:**
- **Zero code required** — one YAML config file drives everything
- **No dependency on `eds_core`** — `eds_loader` is fully standalone
- **Idempotent (full mode)** — every full run is a complete replace; running twice gives the same result
- **Incremental (delta mode)** — SHA-256 hash detection; only changed datasets are upserted
- **Extensible** — new connectors plug in without changing core code
- **Observable** — metrics file, run history log, notifications, status/history/diff CLI commands
- **Data quality** — row-level validation with 7 rule types; schema drift detection between runs

---

## 2. Technology Stack

### Core Runtime

| Technology | Version | Role |
|---|---|---|
| **Python** | >= 3.12 | Runtime language |
| **Polars** | >= 1.0 | DataFrame engine — reads all file formats, moves data between connectors |
| **Pydantic** | >= 2.7 | Config validation — validates `loader.yaml` fields and types |
| **Typer** | >= 0.12 | CLI framework — `eds-loader run`, `validate`, `init`, `connectors` commands |
| **PyYAML** | >= 6.0 | Parses the `loader.yaml` config file |

### Optional Driver Packages (one per connector)

| Package | Connector | Install |
|---|---|---|
| `psycopg` v3 | PostgreSQL | `eds-loader[postgres]` |
| `pymysql` | MySQL | `eds-loader[mysql]` |
| `pyodbc` | Microsoft SQL Server | `eds-loader[mssql]` |
| `oracledb` v2+ | Oracle Database | `eds-loader[oracle]` |
| `pymongo` | MongoDB | `eds-loader[mongodb]` |
| `google-cloud-bigquery` | Google BigQuery | `eds-loader[bigquery]` |
| `elasticsearch` v8+ | Elasticsearch / OpenSearch | `eds-loader[elasticsearch]` |
| `paramiko` | SSH / SFTP | `eds-loader[remote_fs]` |
| `boto3` | AWS S3 | `eds-loader[s3]` |
| `azure-storage-blob` | Azure Blob Storage | `eds-loader[azure_blob]` |
| `google-cloud-storage` | Google Cloud Storage | `eds-loader[gcs]` |
| `fastexcel` | Excel source files | `eds-loader[excel]` |

### Build & Dev Tooling

| Tool | Role |
|---|---|
| **Hatchling** | Build backend — creates the installable wheel |
| **pytest >= 8.0** | Test runner |
| **ruff** | Linter and code style checker |
| **mypy** | Static type checker |
| **types-PyYAML** | Type stubs for PyYAML |

### Why Polars (not Pandas)?

Polars was chosen because:
- **Much faster** for large datasets (written in Rust, uses Apache Arrow internally)
- **Native Parquet support** with no extra dependencies
- **All formats in one library** — CSV, JSON, NDJSON, Avro, ORC, Excel
- **Type safety** — Polars DataFrames have strict, explicit schemas
- `df.to_dicts()` converts rows to Python dicts for MongoDB/pyodbc bulk insert
- `df.rows()` produces tuples for SQL `executemany()`

---

## 3. Project Structure

```
eds_loader/                        <- project root
|- pyproject.toml                  <- package metadata, all extras, build config
|- README.md                       <- quick-start + full connector reference
|- CHANGELOG.md                    <- version history
|- user_guide.md                   <- complete step-by-step user guide
|- ARCHITECTURE.md                 <- this file
|- LICENSE
|
+-- eds_loader/                    <- Python package
    |- __init__.py                 <- public API + connector imports (triggers registration)
    |- version.py                  <- __version__ = "0.4.0"
    |- config.py                   <- LoaderConfig + ConnectorConfig (Pydantic), ENV-var interpolation
    |- loader.py                   <- load() — core orchestrator (full + incremental modes)
    |- exceptions.py               <- exception hierarchy
    |- _logging.py                 <- daily rotating file logging setup
    |- _progress.py                <- live terminal progress bar (logging.Handler subclass)
    |- _state.py                   <- state file: DatasetState, RunState, SHA-256 hashing, schema fingerprints
    |- _metrics.py                 <- RunMetrics + write_metrics() — JSON run statistics
    |- _run_log.py                 <- append_run_log() / read_run_log() — JSONL history
    |- _notifications.py           <- dispatch_notifications() — email/Slack/Teams/webhook
    |- _validation.py              <- validate_dataset() — 7 rule types + quarantine
    |- _schema_drift.py            <- detect_drift() — added/removed/type-changed columns
    |
    +-- cli/
    |   |- __init__.py
    |   |- main.py                 <- Typer app: run, status, reset, history, diff,
    |   |                             validate, init, connectors
    |   +-- _templates.py          <- YAML config templates for `eds-loader init`
    |                                 (all connectors + all v0.4 sections)
    |
    +-- connectors/
        |- __init__.py             <- re-exports public connector API
        |- base.py                 <- Readable / Writable / Upsertable protocols
        |                            WriteResult / UpsertResult dataclasses
        |- registry.py             <- ConnectorSpec, CONNECTORS dict, register/get functions
        |- _formats.py             <- format registry (parquet/csv/json/ndjson/excel/avro/orc)
        |- _sql_base.py            <- BaseSQLConnector (shared DDL, FK sort, bulk insert, upsert)
        |- _cloud_base.py          <- CloudBaseConnector (shared S3/Azure/GCS read/write)
        |- local_fs.py             <- LocalFSConnector
        |- remote_fs.py            <- RemoteFSConnector (SSH/SFTP via paramiko)
        |- postgres.py             <- PostgresConnector
        |- mysql.py                <- MySQLConnector
        |- mssql.py                <- MSSQLConnector
        |- mongodb.py              <- MongoDBConnector
        |- oracle.py               <- OracleConnector       (NEW v0.4)
        |- bigquery.py             <- BigQueryConnector     (NEW v0.4)
        |- elasticsearch_connector.py <- ElasticsearchConnector (NEW v0.4)
        |- s3.py                   <- S3Connector
        |- azure_blob.py           <- AzureBlobConnector
        +-- gcs.py                 <- GCSConnector
```

---

## 4. Architecture Overview

```
+----------------------------------------------------------------------+
|                        USER ENTRY POINTS                             |
|                                                                      |
|   CLI: eds-loader run -c loader.yaml                                 |
|   Python API: result = load(LoaderConfig.from_yaml("loader.yaml"))   |
+----------------------------------+-----------------------------------+
                                   |
                                   v
+----------------------------------------------------------------------+
|                     CONFIG LAYER  (config.py)                        |
|                                                                      |
|  loader.yaml -> yaml.safe_load() -> Pydantic validation              |
|                                      |- LoaderConfig                 |
|                                      |   |- source: ConnectorConfig  |
|                                      |   |- target: ConnectorConfig  |
|                                      |   |- tables: list[str]        |
|                                      |   |- enforce_constraints      |
|                                      |   +- schema_required          |
|                                      +- ConnectorConfig              |
|                                          |- kind: str                |
|                                          +- **extra_fields           |
+----------------------------------+-----------------------------------+
                                   |
                                   v
+----------------------------------------------------------------------+
|                    REGISTRY LAYER  (registry.py)                     |
|                                                                      |
|  CONNECTORS dict -> get_connector(kind, config)                      |
|  (populated at import time by each connector's self-registration)    |
|                                                                      |
|  ConnectorSpec {           _is_package_available(pkg)                |
|    kind                      importlib.import_module(pkg)            |
|    class                     -> True if installed, False if missing  |
|    packages              }                                           |
|    can_read / can_write                                              |
+----------------------------------+-----------------------------------+
                                   |
                                   v
+----------------------------------------------------------------------+
|                    CORE LOADER  (loader.py)                          |
|                                                                      |
|  load(config):                                                       |
|    1. Instantiate source connector                                   |
|    2. Instantiate target connector                                   |
|    3. Verify source is Readable, target is Writable                  |
|    4. Read schema.json  (if schema_required=True)                    |
|    5. Determine tables to load                                       |
|    6. Read datasets  (Polars DataFrames)                             |
|    7. Write datasets to target                                       |
|    8. Return LoadResult                                              |
+-------------------+---------------------------+---------------------+
                    |                           |
                    v                           v
  +-----------------------+       +-------------------------+
  |  SOURCE CONNECTORS    |       |   TARGET CONNECTORS     |
  |  (Readable protocol)  |       |   (Writable protocol)   |
  |                       |       |                         |
  |  local_fs             |       |  local_fs               |
  |  remote_fs (SSH)      |       |  remote_fs (SSH)        |
  |  s3                   |       |  s3                     |
  |  azure_blob           |       |  azure_blob             |
  |  gcs                  |       |  gcs                    |
  |                       |       |  postgres               |
  |                       |       |  mysql                  |
  |                       |       |  mssql                  |
  |                       |       |  mongodb                |
  +-----------------------+       +-------------------------+
```

---

## 5. Core Concepts

### schema.json

The **key metadata file** written by `eds_core` alongside the data files.
`eds_loader` reads it to know table structure, primary keys, foreign keys,
and unique columns — enabling DDL generation and FK-ordered writes.

```json
{
  "customers": {
    "columns": {
      "customer_id": "Int64",
      "email":       "String",
      "name":        "String"
    },
    "primary_key":    "customer_id",
    "unique_columns": ["email"],
    "foreign_keys":   []
  },
  "orders": {
    "columns": {
      "order_id":    "Int64",
      "customer_id": "Int64",
      "amount":      "Float64"
    },
    "primary_key":    "order_id",
    "unique_columns": [],
    "foreign_keys": [
      {
        "column":            "customer_id",
        "references":        "customers",
        "referenced_column": "customer_id",
        "nullable":          false
      }
    ]
  }
}
```

### Readable / Writable Protocols (PEP 544)

These are **structural protocols** — like interfaces in Java/C#. A connector
does NOT need to inherit from a base class; it just needs to implement the
right methods and Python automatically recognises it:

```python
# A connector is Readable if it has these two methods:
def read_schema_metadata(self) -> dict[str, Any]: ...
def read_datasets(self, names: list[str] | None) -> dict[str, pl.DataFrame]: ...

# A connector is Writable if it has this method:
def write_datasets(self, datasets: dict, schema_metadata: dict) -> list[WriteResult]: ...
```

### WriteResult

Every connector returns one `WriteResult` per dataset written:

```python
@dataclass(frozen=True, slots=True)
class WriteResult:
    dataset:  str   # e.g. "customers"
    location: str   # e.g. "postgresql://localhost/eds_db/public/customers"
    rows:     int   # e.g. 12500
```

---

## 6. Full Code Flow — Step by Step

This traces exactly what happens when you run:
```bash
eds-loader run --config loader.yaml
```

### Step 1: CLI Entry Point (`cli/main.py`)

```
eds-loader run --config loader.yaml
    |
    v
Typer calls run_cmd(config_file=Path("loader.yaml"), dry_run=False)
    |
    |- configure_logging()        <- creates logs/2026-08-20.log
    |- TerminalProgress()         <- attaches live progress bar to stderr
    |
    v
LoaderConfig.from_yaml(config_file)
```

### Step 2: Config Parsing (`config.py`)

```
loader.yaml file
    |
    v  path.read_text()
raw YAML text
    |
    v  yaml.safe_load()
Python dict: {
  "source": {"kind": "local_fs", "path": "./output"},
  "target": {"kind": "mongodb",  "host": "localhost", "database": "eds_db"},
  "tables": [],
  "enforce_constraints": false,
  "schema_required": false
}
    |
    v  LoaderConfig.model_validate(raw)
    |
    |- Pydantic validates every field type
    |- model_validator: no blank table names
    +- Returns LoaderConfig object OK
```

### Step 3: Load Orchestration (`loader.py`)

```
load(config)
    |
    v  get_connector("local_fs", {"path": "./output"})
    |
    |- Registry lookup: CONNECTORS["local_fs"]
    |- _is_package_available check -> (no extra packages needed)
    +- LocalFSConnector(path="./output") instantiated OK

    v  get_connector("mongodb", {"host": "localhost", "database": "eds_db"})
    |
    |- Registry lookup: CONNECTORS["mongodb"]
    |- _is_package_available("pymongo") -> importlib.import_module("pymongo") -> OK
    +- MongoDBConnector(host="localhost", database="eds_db") instantiated OK

    v  isinstance(source, Readable)?   -> OK (has read_schema_metadata + read_datasets)
    v  isinstance(target, Writable)?   -> OK (has write_datasets)

    v  if schema_required=True:
    |      source.read_schema_metadata() -> reads schema.json -> dict
    |      determine tables_to_load = all keys from schema OR config.tables subset
    |
    v  if schema_required=False:
    |      skip schema.json entirely
    |      names_to_load = config.tables or None (auto-discover)

    v  source.read_datasets(names=names_to_load)
    |      -> returns dict[str, pl.DataFrame]
    |         {"customers": DataFrame(12500 rows), "orders": DataFrame(47200 rows)}

    v  if enforce_constraints=True:
    |      effective_metadata = {k:v for k,v in schema if k in datasets}
    |  else:
    |      effective_metadata = {}   (no constraints forwarded)

    v  target.write_datasets(datasets, effective_metadata)
    |      -> returns list[WriteResult]

    v  return LoadResult(
           tables_written=["customers", "orders"],
           rows_written={"customers": 12500, "orders": 47200},
           write_results=[...]
       )
```

### Step 4: CLI Output (`cli/main.py`)

```
+-------------+--------+---------------------------------------------+
| Table       |   Rows | Location                                    |
+-------------+--------+---------------------------------------------+
| customers   | 12,500 | mongodb://localhost:27017/eds_db/customers  |
| orders      | 47,200 | mongodb://localhost:27017/eds_db/orders     |
+-------------+--------+---------------------------------------------+

Done -- 59,700 rows across 2 table(s) in 3.1 s.
```

---

## 7. The Connector System — Deep Dive

### Storage Connectors (Readable + Writable)

These connectors can act as **source OR target**. They read/write files.

#### `LocalFSConnector` (`local_fs.py`)

```
READ flow:
  path/
  |- schema.json    <- read_schema_metadata() -> json.loads()
  |- customers.csv  <- read_datasets() -> _formats.read_path("csv", file)
  +- orders.parquet <- read_datasets() -> _formats.read_path("parquet", file)

WRITE flow:
  path/ (created if missing)
  |- schema.json (merged with existing)
  |- customers.parquet  <- df.write_parquet()
  +- orders.parquet     <- df.write_parquet()
```

#### `RemoteFSConnector` (`remote_fs.py`)

```
Auth modes:
  1. password / password_env
  2. private_key_path + private_key_passphrase_env
  3. SSH agent (fallback if neither set)

Connection (lazy -- opened on first read/write call):
  paramiko.SSHClient().connect(host, port, username, ...)
  client.open_sftp()  ->  SFTPClient

READ:  sftp.open(remote_path/schema.json) -> json.loads()
       sftp.open(remote_path/name.parquet) -> io.BytesIO -> _formats.read_bytes()
WRITE: sftp.putfo(io.BytesIO(df.write_parquet()), remote_path/name.parquet)
```

#### Cloud Connectors (S3 / Azure Blob / GCS)

All three share `CloudBaseConnector` which implements the full read/write logic.
Each subclass only overrides 5 primitive methods:

```
CloudBaseConnector (abstract)
    |
    |- _connect()              <- create cloud client (boto3 / azure SDK / GCS SDK)
    |- _list_parquet_keys()    <- list files under prefix
    |- _read_bytes(key)        <- download file as raw bytes
    |- _write_bytes(key, data) <- upload bytes to cloud
    +- _location(name)         <- format the location URL string

Shared logic in base (same for all cloud connectors):
    read_schema_metadata() -> _read_bytes("schema.json") -> json.loads()
    read_datasets()        -> _list_parquet_keys() -> for each: _read_bytes() -> read_bytes()
    write_datasets()       -> for each df: write_parquet() -> _write_bytes()
                              if schema: json.dumps() -> _write_bytes("schema.json")
```

---

### Database Connectors (Writable only)

Database connectors are **write-only targets** — they receive DataFrames
and write them as tables/collections.

#### SQL Family — `BaseSQLConnector` (`_sql_base.py`)

PostgreSQL, MySQL, and MSSQL all inherit from this base class.

```
write_datasets(datasets, schema_metadata):
    |
    v  1. _ensure_namespace_sql()
    |        Postgres: CREATE SCHEMA IF NOT EXISTS "public"
    |        MySQL:    CREATE DATABASE IF NOT EXISTS `eds_db`
    |        MSSQL:    IF NOT EXISTS... EXEC('CREATE SCHEMA [dbo]')
    |
    v  2. _pre_drop_hook()
    |        MySQL:   SET FOREIGN_KEY_CHECKS = 0
    |        MSSQL:   DROP all FK constraints in schema  (T-SQL workaround)
    |        Postgres: (no-op -- DROP ... CASCADE handles it)
    |
    v  3. Topological sort -- FK dependency order
    |        Example: "customers" must be created BEFORE "orders"
    |        because orders.customer_id -> customers.customer_id
    |
    v  4. For each table in sorted order:
    |        DROP TABLE IF EXISTS <table>
    |        CREATE TABLE <table> (col_defs...)
    |        INSERT INTO <table> ... executemany(rows)
    |        COMMIT
    |
    v  5. _post_write_hook()
    |        MySQL: SET FOREIGN_KEY_CHECKS = 1  (always runs, even on error)
    |
    v  return list[WriteResult]
```

**Polars -> SQL type maps per dialect:**

| Polars Type | Postgres | MySQL | MSSQL |
|---|---|---|---|
| `Int32` | `INTEGER` | `INT` | `INT` |
| `Int64` | `BIGINT` | `BIGINT` | `BIGINT` |
| `Float64` | `DOUBLE PRECISION` | `DOUBLE` | `FLOAT` |
| `String` | `TEXT` | `TEXT` | `NVARCHAR(MAX)` |
| `Boolean` | `BOOLEAN` | `TINYINT(1)` | `BIT` |
| `Date` | `DATE` | `DATE` | `DATE` |
| `Datetime` | `TIMESTAMP` | `DATETIME` | `DATETIME2` |
| `List/Struct` | `JSONB` | `JSON` | `NVARCHAR(MAX)` |

#### `MongoDBConnector` (`mongodb.py`)

```
write_datasets(datasets, schema_metadata):
    |
    v  For each dataset (no topological sort -- collections are independent):
    |
    |    1. collection.drop()               <- full replace
    |    2. Cast Date -> Datetime columns   <- BSON can't encode datetime.date
    |    3. collection.insert_many(
    |           df.to_dicts()               <- Polars rows -> Python dicts -> BSON
    |       )
    |    4. if schema_metadata:
    |         create_index(pk_col, unique=True)
    |         create_index(unique_col, unique=True)  for each
    |         create_index(fk_col, unique=False)     for each
    |
    v  return list[WriteResult]
      location = "mongodb://host:port/database/collection"
```

---

## 8. The Registry System — How Connectors Self-Register

### At Import Time (Module Level Code)

Every connector file ends with:

```python
# bottom of mongodb.py -- runs ONCE when the module is first imported
register_connector(
    "mongodb",                          # <- kind name used in YAML
    ConnectorSpec(
        connector_class=MongoDBConnector if _PYMONGO_AVAILABLE else None,
        required_packages=["pymongo"],  # <- checked at runtime by _is_package_available
        install_extra="mongodb",        # <- used in pip install hint
        can_read=False,
        can_write=True,
        description="MongoDB -- writes datasets as document collections.",
    ),
)
```

### `__init__.py` Triggers All Registrations

```python
# eds_loader/__init__.py -- runs when you import eds_loader or use the CLI
import eds_loader.connectors.local_fs    # -> register_connector("local_fs", ...)
import eds_loader.connectors.remote_fs   # -> register_connector("remote_fs", ...)
import eds_loader.connectors.postgres    # -> register_connector("postgres", ...)
import eds_loader.connectors.mysql       # -> register_connector("mysql", ...)
import eds_loader.connectors.mssql       # -> register_connector("mssql", ...)
import eds_loader.connectors.mongodb     # -> register_connector("mongodb", ...)
import eds_loader.connectors.s3          # -> register_connector("s3", ...)
import eds_loader.connectors.azure_blob  # -> register_connector("azure_blob", ...)
import eds_loader.connectors.gcs         # -> register_connector("gcs", ...)
```

### Runtime Install Check

```python
def _is_package_available(package: str) -> bool:
    try:
        importlib.import_module(package)   # <- actually runs "import pymongo"
        return True
    except (ImportError, ModuleNotFoundError):
        pass
    # also tries: "azure-storage-blob" -> "azure_storage_blob"
    normalised = package.replace("-", "_")
    ...
    return False
```

---

## 9. The Format System — Multi-Format Source Support

`_formats.py` decouples file format handling from all connector implementations.

### Supported Formats

| Format | Extension(s) | Polars Reader | Extra dep |
|---|---|---|---|
| `parquet` | `.parquet` | `pl.read_parquet()` | None (always available) |
| `csv` | `.csv` | `pl.read_csv()` | None |
| `json` | `.json` | `pl.read_json()` | None |
| `ndjson` | `.ndjson`, `.jsonl` | `pl.read_ndjson()` | None |
| `excel` | `.xlsx`, `.xls` | `pl.read_excel()` | `openpyxl` |
| `avro` | `.avro` | `pl.read_avro()` | None |
| `orc` | `.orc` | `pl.read_orc()` | None |

### How It Works

```python
# Config:  format: csv

LocalFSConnector(path="./data", format="csv")
    |
    v  read_datasets(names=None)
    |
    |- all_extensions("csv")  -> [".csv"]
    |- glob("*.csv")          -> ["customers.csv", "orders.csv"]
    |- for each file:
    |      _formats.read_path("csv", file_path)
    |          -> pl.read_csv(path)
    |          -> {"customers": DataFrame}
    +- return {"customers": df1, "orders": df2}
```

### Two Read Functions

```python
read_path(fmt, path)          # local_fs -- file is on local disk
read_bytes(fmt, stem, data)   # cloud + remote_fs -- file arrives as bytes
```

### Excel Multi-Sheet Behaviour

```
sales.xlsx  with sheets: Jan, Feb, Mar
    |
    v  pl.read_excel("sales.xlsx", sheet_name=None)
    |  -> {"Jan": df1, "Feb": df2, "Mar": df3}
    |
    v  _sheets_to_datasets("sales", sheets):
       3 sheets -> {"sales_Jan": df1, "sales_Feb": df2, "sales_Mar": df3}
       1 sheet  -> {"sales": df}
```

---

## 10. SQL Base Layer — Shared Database Logic

### Why FK Order Matters

If you create `orders` before `customers`, the database raises a FK constraint
error because `orders.customer_id` references `customers.customer_id` which
doesn't exist yet. Parent tables must always be created first.

### Topological Sort Algorithm

```python
# schema_metadata has:
# customers:   no FK deps
# orders:      FK -> customers
# order_items: FK -> orders

deps = {
    "customers":   set(),
    "orders":      {"customers"},
    "order_items": {"orders"},
}

# Round 1: "customers" has no deps -> add to result
# Round 2: "orders" depends on "customers" (already done) -> add to result
# Round 3: "order_items" depends on "orders" (already done) -> add to result
# Final: ["customers", "orders", "order_items"]
```

Self-referencing FKs (e.g. `categories.parent_id -> categories.id`) are
**excluded** from the dependency graph because the column is in the same
`CREATE TABLE` statement and does not cause ordering conflicts.

---

## 11. The Config System

### YAML -> Pydantic -> Connector kwargs

```
loader.yaml:
  source:
    kind: s3
    bucket: my-bucket
    format: csv
    aws_secret_access_key_env: AWS_SECRET_ACCESS_KEY

                v  yaml.safe_load()

raw dict: {"kind": "s3", "bucket": "my-bucket", "format": "csv",
           "aws_secret_access_key_env": "AWS_SECRET_ACCESS_KEY"}

                v  ConnectorConfig(extra="allow")  <- captures ALL extra fields

ConnectorConfig:
  kind = "s3"
  bucket = "my-bucket"           <- extra field
  format = "csv"                 <- extra field
  aws_secret_access_key_env = "AWS_SECRET_ACCESS_KEY"  <- extra field

                v  config.source.extra_fields()

{"bucket": "my-bucket", "format": "csv",
 "aws_secret_access_key_env": "AWS_SECRET_ACCESS_KEY"}

                v  S3Connector(**extra_fields)

S3Connector(bucket="my-bucket", format="csv",
            aws_secret_access_key_env="AWS_SECRET_ACCESS_KEY")
```

`ConnectorConfig` uses `extra="allow"` — any connector-specific fields
are captured without validation at config level and passed through as
keyword arguments to the connector constructor.

### `LoaderConfig` Top-Level Fields

| Field | Type | Default | Purpose |
|---|---|---|---|
| `source` | `ConnectorConfig` | required | Where to read data from |
| `target` | `ConnectorConfig` | required | Where to write data to |
| `tables` | `list[str]` | `[]` | Subset of tables; empty = load all |
| `enforce_constraints` | `bool` | `True` | Forward schema metadata to target for PK/FK/UNIQUE |
| `schema_required` | `bool` | `True` | When False, skip schema.json; auto-discover files |

---

## 12. Logging & Progress System

### Two Parallel Output Channels

```
eds-loader run
         |
         +------> logs/2026-08-20.log  (ALL events: DEBUG+INFO+ERROR, full text)
         |        format: "2026-08-20 11:00:01  INFO  eds_loader.loader  Starting..."
         |
         +------> stderr (terminal only -- single self-updating line)
                  format: "Writing datasets [########--------] 2/3  orders"
                  (updates in-place using carriage-return \r)
```

### How Progress Works Without Coupling

Connectors never import or reference `TerminalProgress`. They just add a
`progress` dict to specific log calls:

```python
# Inside mongodb.py:
logger.info(
    "[%s] wrote %d document(s)", name, df.height,
    extra={"progress": {"stage": "write", "current": i, "total": total, "label": name}},
)
```

`TerminalProgress` is a `logging.Handler`. It intercepts log records
with a `progress` key in `extra` and renders the bar. All other records
are ignored by the progress handler (but still go to the log file).

### Daily Log File Rotation

```python
today = datetime.date.today().isoformat()   # "2026-08-20"
log_path = Path("logs") / f"{today}.log"    # "logs/2026-08-20.log"
# Each day = new file. Same day = append to same file.
# If logs/ can't be created -> silently disabled, run continues normally.
```

---

## 13. Exception Hierarchy

```
LoaderError  (base -- catch all loader failures with one except clause)
    |
    +-- ConfigError                    Exit code: 2
    |     - YAML file not found or invalid
    |     - Pydantic validation failed
    |     - Table name not in schema.json
    |     - Connector role mismatch (e.g. postgres used as source)
    |
    +-- ConnectorNotFoundError         Exit code: 2
    |     - kind: "xyz" not in registry
    |     - Message includes all known kinds
    |
    +-- ConnectorNotInstalledError     Exit code: 2
    |     - kind is registered but driver is missing
    |     - Message includes exact pip install command to fix
    |
    +-- LoadError                      Exit code: 3
          - Network failure (SSH, DB connection, cloud API)
          - File not found at source
          - Database write error (constraint violation, disk full)
          - Environment variable set in config but missing at runtime
          - schema.json missing or invalid JSON
```

---

## 14. All Real-World Scenarios

### Scenario 1: Local Parquet -> PostgreSQL (development default)

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
  schema: synthetic

enforce_constraints: true
schema_required: true
```

Flow: Read schema.json -> FK-sort tables -> DROP/CREATE/COPY each table

---

### Scenario 2: Local CSV -> MongoDB (no schema.json)

```yaml
source:
  kind: local_fs
  path: ./healthcare_data
  format: csv

target:
  kind: mongodb
  host: localhost
  database: healthcare_db

schema_required: false
enforce_constraints: false
```

Flow: Discover *.csv files -> read_csv() each -> drop+insert_many() per collection

---

### Scenario 3: S3 -> PostgreSQL (production CI/CD)

```yaml
source:
  kind: s3
  bucket: eds-prod-outputs
  prefix: runs/2026-08-20/
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

Flow: boto3 lists S3 keys -> download schema.json + parquets -> FK-sort -> write to Postgres

---

### Scenario 4: SSH Server -> SQL Server (MSSQL)

```yaml
source:
  kind: remote_fs
  host: data-server.example.com
  username: eds_reader
  remote_path: /exports/eds
  password_env: SFTP_PASSWORD

target:
  kind: mssql
  host: 192.168.1.100
  database: eds_db
  user: eds_sa
  password_env: EDS_MSSQL_PASSWORD
  driver: "ODBC Driver 17 for SQL Server"
  trust_server_certificate: true
```

Flow: paramiko SFTP -> download files -> MSSQL drop all FK constraints ->
DROP/CREATE/INSERT with fast_executemany -> COMMIT

---

### Scenario 5: Excel Multi-Sheet -> Multiple MongoDB Collections

```yaml
source:
  kind: local_fs
  path: ./reports
  format: excel

target:
  kind: mongodb
  host: localhost
  database: reports_db

schema_required: false
enforce_constraints: false
```

Flow: sales.xlsx with sheets Jan/Feb/Mar -> 3 collections: sales_Jan, sales_Feb, sales_Mar

---

### Scenario 6: Local -> S3 (archive Parquet to cloud)

```yaml
source:
  kind: local_fs
  path: ./output

target:
  kind: s3
  bucket: my-archive-bucket
  prefix: eds/2026-08-20/
  aws_secret_access_key_env: AWS_SECRET_ACCESS_KEY
```

Flow: Read local files -> upload each as S3 object -> upload schema.json
Result: S3 can now be used as a source for a future load

---

### Scenario 7: Azure Blob -> GCS (cloud-to-cloud migration)

```yaml
source:
  kind: azure_blob
  account_name: myazureaccount
  container: eds-data
  account_key_env: AZURE_STORAGE_KEY

target:
  kind: gcs
  bucket: my-gcs-bucket
  prefix: migrated/
  credentials_env: GOOGLE_APPLICATION_CREDENTIALS
```

Flow: Azure SDK downloads blobs -> GCS SDK uploads each file

---

### Scenario 8: Dry Run (preview without writing)

```bash
eds-loader run -c loader.yaml --dry-run
```

Flow: Read source -> display table names + column counts + row counts -> EXIT
Target is NEVER touched. Use this before any production load.

```
DRY RUN -- no data will be written.

  customers   3 cols, 12,500 rows
  orders      5 cols, 47,200 rows

Total: 59,700 rows across 2 dataset(s).
Run without --dry-run to write.
```

---

### Scenario 9: Load Specific Tables Only

```yaml
tables:
  - customers
  - products
# orders will NOT be loaded
```

Flow: Validates names in schema.json -> FK sort only within these 2 tables ->
read + write only these 2 datasets

---

### Scenario 10: Python API — Programmatic Integration

```python
import os
from eds_loader import load
from eds_loader.config import LoaderConfig

config = LoaderConfig(
    source={"kind": "local_fs", "path": "./output"},
    target={
        "kind": "postgres",
        "host": os.environ["DB_HOST"],
        "database": "eds_db",
        "user": "eds_loader",
        "password_env": "DB_PASSWORD",
    },
    tables=[],
    enforce_constraints=True,
    schema_required=True,
)

result = load(config)

print(f"Total rows: {result.total_rows:,}")
for r in result.write_results:
    print(f"  {r.dataset}: {r.rows:,} rows -> {r.location}")
```

---

## 15. Data Flow Diagrams

### Normal Flow (schema_required=True)

```
loader.yaml
    |
    v  LoaderConfig.from_yaml()
LoaderConfig (validated)
    |
    +-> Source Connector -> read_schema_metadata() -> schema dict
    |                                                       |
    |                        read_datasets(names) <---------+
    |                             |
    |                             v
    |                    dict[str, pl.DataFrame]
    |                             |
    +-> Target Connector <--------+
          write_datasets(datasets, schema_metadata)
              |
              v
         list[WriteResult]
              |
              v
    LoadResult(tables_written, rows_written, total_rows, write_results)
```

### Schema-Free Flow (schema_required=False)

```
loader.yaml  (schema_required: false)
    |
    v
Source Connector
    |  <- NO schema.json read
    v
Auto-discover *.format files at source
    |
    v
read_datasets(names=None)
    |
    v
dict[str, pl.DataFrame]
    |
    v
Target Connector
write_datasets(datasets, schema_metadata={})  <- empty dict, no constraints
    |
    v
list[WriteResult]
```

### SQL Write Flow (all SQL database targets)

```
write_datasets called
    |
    v  _ensure_namespace_sql()   -- CREATE SCHEMA / DATABASE if not exists
    v  _pre_drop_hook()          -- MySQL: disable FK checks / MSSQL: drop FK constraints
    v  _topological_sort()       -- order tables by FK deps
    |
    +-- for each table in sorted order:
    |       DROP TABLE IF EXISTS
    |       CREATE TABLE (column defs from Polars schema + constraints)
    |       INSERT rows via executemany (driver bulk insert)
    |       COMMIT
    |
    v  _post_write_hook()        -- MySQL: re-enable FK checks (always runs)
    v  return [WriteResult, ...]
```

---

## 16. Security — Credential Handling

### Two Config Styles

```yaml
# Style 1: Inline (local dev only, NEVER commit)
target:
  password: "my-secret"

# Style 2: Env-var (production, safe to commit)
target:
  password_env: EDS_PG_PASSWORD    # <- only the NAME is in the YAML
```

```bash
# Set the actual value in your environment:
export EDS_PG_PASSWORD="actual-secret-here"
eds-loader run -c loader.yaml
```

### What NEVER Appears in Logs or Error Messages

The code is specifically designed so credential values never leak:

```python
# WRONG (never done):
#   logger.info("Connecting with password=%s", self._password)

# CORRECT (only the variable NAME is mentioned, never the value):
raise LoadError(
    f"Environment variable {self._password_env!r} is not set."
    # Output: "Environment variable 'EDS_PG_PASSWORD' is not set."
    # The actual password is never referenced anywhere
)
```

---

## 17. How to Add a New Connector

### Option A — New SQL Database (e.g. Oracle)

```python
# eds_loader/connectors/oracle.py
from eds_loader.connectors._sql_base import BaseSQLConnector
from eds_loader.connectors.registry import ConnectorSpec, register_connector

class OracleConnector(BaseSQLConnector):
    def _connect(self): ...          # override: open oracledb connection
    def _disconnect(self): ...       # override: close connection
    def _quote(self, name): ...      # override: double-quote identifiers
    def _table_ref(self, name): ...  # override: "SCHEMA"."TABLE"
    def _sql_type_map(self): ...     # override: Polars -> Oracle type map
    def _drop_table_sql(self): ...   # override: DROP TABLE IF EXISTS ...
    def _build_location(self): ...   # override: oracle://host/db/schema.table

register_connector("oracle", ConnectorSpec(
    connector_class=OracleConnector if _ORACLEDB_AVAILABLE else None,
    required_packages=["oracledb"],
    install_extra="oracle",
    can_read=False, can_write=True,
))
```

Then add to `__init__.py`:
```python
import eds_loader.connectors.oracle   # noqa: F401
```

And to `pyproject.toml`:
```toml
oracle = ["oracledb>=2.0", "sqlalchemy>=2.0"]
```

### Option B — New Cloud Storage

```python
# eds_loader/connectors/backblaze_b2.py
from eds_loader.connectors._cloud_base import CloudBaseConnector

class B2Connector(CloudBaseConnector):
    def _connect(self): ...               # create B2 SDK client
    def _list_parquet_keys(self): ...     # list files under prefix
    def _read_bytes(self, key): ...       # download file as bytes
    def _write_bytes(self, key, data): ...# upload bytes
    def _location(self, name): ...        # "b2://bucket/prefix/name.parquet"

register_connector("b2", ConnectorSpec(..., can_read=True, can_write=True))
```

### Option C — Completely Custom (no base class needed)

Just implement the Readable/Writable protocol methods directly. Python uses
structural conformance — no inheritance required:

```python
class MyCustomTarget:
    def write_datasets(self, datasets, schema_metadata):
        results = []
        for name, df in datasets.items():
            # your custom write logic here
            results.append(WriteResult(dataset=name, location="...", rows=df.height))
        return results

register_connector("my_target", ConnectorSpec(
    connector_class=MyCustomTarget,
    required_packages=[],
    install_extra="",
    can_read=False, can_write=True,
))
```

---

*Last updated: 2026-08-20 | Version: 0.2.0 | Author: Makin Laboratories*
