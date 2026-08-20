# Changelog

All notable changes to `eds-loader` are documented here.
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.0] — 2026-08-20

### Added

**Step 10 — Microsoft SQL Server connector**
- `MSSQLConnector` — writes datasets to SQL Server using `pyodbc` with
  `fast_executemany` for bulk inserts.
- Square-bracket identifier quoting (`[schema].[table]`) and T-SQL type map.
- `_pre_drop_hook`: drops every foreign-key constraint in the target schema
  before `DROP TABLE` (T-SQL has no per-session `DISABLE FK CHECKS` switch).
- `_indexable_string_type`: promotes `NVARCHAR(MAX)` → `NVARCHAR(255)` for
  PK/UNIQUE/FK index columns (SQL Server rejects `MAX` as a key column).
- Config fields: `host`, `database`, `user`, `password`/`password_env`, `port`,
  `schema`, `driver`, `encrypt`, `trust_server_certificate`, `connect_timeout`.
- Optional extra: `pip install eds-loader[mssql]`.
- `oracle` extra stub added to `pyproject.toml`: `oracledb>=2.0` +
  `sqlalchemy>=2.0`. (Connector implementation planned.)

**Schema-optional loading (`schema_required`)**
- `LoaderConfig` gains a `schema_required: bool` field (default `True`).
- When `False`, `schema.json` is skipped entirely; datasets are
  auto-discovered by listing `*.parquet` (or other format) files from the
  source. Constraint enforcement is automatically disabled.
- `eds-loader run` and `eds-loader validate` both honour this flag.
- Enables loading raw Parquet dumps that have no EDS schema file.

**Multi-format source support**
- `eds_loader.connectors._formats` — central format registry supporting:
  `parquet` (default), `csv`, `json`, `ndjson`, `excel`, `avro`, `orc`.
- All source connectors (`local_fs`, `remote_fs`, `s3`, `azure_blob`, `gcs`)
  accept a `format:` config field to switch the read format.
- Excel multi-sheet behaviour: each sheet becomes a separate dataset named
  `<stem>_<SheetName>`; single-sheet files use the bare stem.
- `excel` optional extra added: `pip install eds-loader[excel]`
  (requires `openpyxl`).
- `read_bytes()` helper shared between cloud and SSH connectors.

### Changed
- `MongoDBConnector`: `connect_timeout` is now documented as milliseconds
  (server-selection timeout), consistent with pymongo semantics.
- `eds-loader validate`: outputs a specific message when
  `schema_required: false` is set, instead of attempting to read
  `schema.json`.

### Documentation
- `README.md`: added MSSQL and Oracle to connector matrix; added `format:`
  field; added `schema_required` to config reference and `LoaderConfig`
  table; added Excel multi-sheet note; added per-test-file run reference.
- `user_guide.md`: added Section 9.9 (MSSQL), multi-format sections;
  `schema_required` use-cases; section ordering fix; expanded troubleshooting.
- `CHANGELOG.md`: this entry.

### Tests
- Added `test_sql_base.py` — shared SQL base-class unit tests.
- All tests use mocked drivers — no real databases or cloud accounts required.

---

## [0.1.0] — 2026-08-10

**Step 1 — Project scaffold & schema export**
- `eds_loader` package skeleton with `pyproject.toml`, `hatchling` build
  backend, and `eds-loader` CLI entry point.
- `eds_loader.version` module (`__version__: str = "0.1.0"`).
- Exception hierarchy: `EDSLoaderError`, `ConfigError`, `LoadError`,
  `ConnectorNotFoundError`, `ConnectorNotInstalledError`.
- `LoaderConfig` and `ConnectorConfig` Pydantic models with YAML loading.
- Connector registry (`register_connector`, `get_connector`, `CONNECTORS`).
- `Readable` / `Writable` structural protocols for connectors.

**Step 2 — Core loader**
- `load()` function: source → schema.json → datasets → target.
- `LoadResult` dataclass with `tables_written`, `rows_written`, `total_rows`,
  `write_results`.
- `WriteResult` dataclass (`dataset`, `location`, `rows`).

**Step 3 — Local filesystem connector**
- `LocalFSConnector` — reads and writes Parquet datasets + `schema.json`
  from/to a local directory.

**Step 4 — SSH/SFTP connector**
- `RemoteFSConnector` — reads and writes over SSH/SFTP using `paramiko`.
- Password and private-key auth; configurable port and remote path.
- Optional extra: `pip install eds-loader[remote_fs]`.

**Step 5 — PostgreSQL connector**
- `PostgresConnector` — writes datasets to Postgres using `psycopg` v3.
- Topological sort for FK-ordered writes; DDL from schema metadata;
  `COPY`-based bulk insert; full transaction safety.
- Optional extra: `pip install eds-loader[postgres]`.

**Step 6 — SQL base layer + MySQL connector**
- `BaseSQLConnector` abstract base: shared DDL, bulk insert, topological sort.
- `MySQLConnector` — subclass for MySQL using `pymysql` + SQLAlchemy dialect;
  backtick quoting, `FOREIGN_KEY_CHECKS` hooks, `DATABASE.table` references.
- Optional extra: `pip install eds-loader[mysql]`.

**Step 7 — MongoDB connector**
- `MongoDBConnector` — writes datasets as MongoDB collections using `pymongo`.
- Full drop + `insert_many`; `create_index` for PK, unique, FK columns.
- No topological sort (collections are independent).
- Optional extra: `pip install eds-loader[mongodb]`.

**Step 8 — Cloud storage connectors**
- `CloudBaseConnector` abstract base: shared read/write Parquet + schema.json
  logic; `names` filter on `read_datasets`.
- `S3Connector` — AWS S3 using `boto3`; boto3 paginator; `endpoint_url` for
  MinIO/LocalStack. Extra: `pip install eds-loader[s3]`.
- `AzureBlobConnector` — Azure Blob Storage using `azure-storage-blob`;
  account key and connection string auth. Extra: `pip install eds-loader[azure]`.
- `GCSConnector` — Google Cloud Storage using `google-cloud-storage`;
  service account JSON and Application Default Credentials.
  Extra: `pip install eds-loader[gcs]`.

**Step 9 — CLI polish & packaging**
- `eds-loader validate --config <file>` — parse, check drivers, probe source.
- `eds-loader init --source <kind> --target <kind>` — generate documented
  starter `loader.yaml` for any connector pair.
- `eds-loader run --dry-run` — preview load without writing.
- Improved `run` output: ASCII table with Dataset / Rows / Location columns
  and elapsed time line.
- `eds_loader.cli._templates` — YAML config templates for all connector kinds.
- Complete `README.md` with connector matrix, config reference, and Python API.
- `pyproject.toml` classifier bump: `3 - Alpha` → `4 - Beta`.

### Tests

- 396 unit and integration tests across all connectors and the CLI.
- All tests use mocked drivers — no real databases or cloud accounts required.
- Test runner: `pytest ≥ 8.0`.

---

*Earlier milestones were tracked in the internal build log.*
