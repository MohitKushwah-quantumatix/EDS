# Changelog

All notable changes to `eds-loader` are documented here.
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.4.0] — 2026-08-25

### Added

**Row-level data validation (`eds_loader/_validation.py`)**
- `validate_dataset()` — applies per-column rules from `schema.json` to a Polars DataFrame.
- 7 supported rule types: `not_null`, `min`, `max`, `min_length`, `max_length`, `allowed_values`, `regex`.
- `ValidationResult` dataclass — carries valid/rejected DataFrames and human-readable violation messages.
- `apply_validation()` — convenience function that enforces the `on_validation_error` policy.
- Three policies controlled by `on_validation_error` in `loader.yaml`:
  - `warn` (default) — log violations, load all rows.
  - `fail` — abort the run on any violation.
  - `quarantine` — load valid rows; write rejected rows to `rejected_dir` as dated Parquet files.
- `quarantine_rejected()` — writes rejected rows to `<rejected_dir>/<dataset>_<date>.parquet`.

**Schema drift detection (`eds_loader/_schema_drift.py`)**
- `detect_drift()` — compares live source schema against stored fingerprint from previous run.
- Detects: added columns, removed columns, type-changed columns.
- `DriftReport` dataclass with `has_drift` property and `summary()` string.
- Three policies via `schema_drift` config field: `warn` (default), `fail`, `ignore`.

**Run metrics file (`eds_loader/_metrics.py`)**
- `RunMetrics` class — captures per-run statistics: status, duration, row counts, per-dataset breakdown.
- `write_metrics()` — atomically writes `run_metrics.json` (temp-file + rename).
- Enable with `metrics_file: auto` in `loader.yaml`.

**Append-only run history log (`eds_loader/_run_log.py`)**
- `append_run_log()` — appends a JSON line to `.eds_loader_runs.jsonl` after every run.
- `read_run_log()` — reads the most recent N entries in reverse-chronological order.
- Powers the new `eds-loader history` CLI command.
- Enable with `run_log_file: auto` in `loader.yaml`.

**Multi-channel notifications (`eds_loader/_notifications.py`)**
- `dispatch_notifications()` — fires channels from the `notifications:` block in `loader.yaml`.
- Four channel kinds: `email` (SMTP/TLS), `slack` (incoming webhook), `teams` (Teams webhook), `webhook` (generic HTTP POST).
- Three trigger keys: `on_failure`, `on_success`, `always`.
- Each channel accepts `password_env` / `webhook_url_env` for secret injection.

**Three new target connectors**
- `connectors/oracle.py` — Oracle Database via `oracledb` v2+.
  - MERGE INTO USING DUAL for upsert; PL/SQL IF-NOT-EXISTS for DDL.
  - Thin mode (default, no Oracle Client) and thick mode.
  - `pip install eds-loader[oracle]`
- `connectors/bigquery.py` — Google BigQuery via `google-cloud-bigquery`.
  - Full load: `WRITE_TRUNCATE`; incremental: BigQuery MERGE DML via staging table.
  - Service account JSON or Application Default Credentials.
  - `pip install eds-loader[bigquery]`
- `connectors/elasticsearch_connector.py` — Elasticsearch / OpenSearch via `elasticsearch` v8+.
  - Full load: delete index + bulk index; incremental: bulk upsert by `_id = pk_value`.
  - Configurable shards, replicas, index prefix.
  - `pip install eds-loader[elasticsearch]`

**Four new CLI commands**
- `eds-loader status -c <file>` — prints config summary, source connectivity probe, and last-run state table.
- `eds-loader reset -c <file>` — deletes the incremental state file (with confirmation prompt); use `--force` to skip.
- `eds-loader history -c <file>` — shows tabular run history from the JSONL log; `--limit N` (default 20).
- `eds-loader diff -c <file>` — reads source and compares against stored state; shows UNCHANGED / CHANGED / NEW per dataset.

**ENV-var interpolation in config YAML**
- `LoaderConfig.from_yaml()` now calls `os.path.expandvars()` before YAML parsing.
- Any `${MY_VAR}` or `$MY_VAR` reference in `loader.yaml` is resolved from the environment at runtime.
- Example: `path: ${DATA_ROOT}/output`, `host: ${DB_HOST}`.

**Performance options**
- `parallelism: N` config field (default `1`) — loads up to N datasets concurrently using `ThreadPoolExecutor`.
- `batch_size: N` config field (default `None`) — write datasets in row chunks to cap peak memory.

**Delete mode for incremental loads**
- `delete_mode` config field (default `keep`):
  - `keep` — deleted source rows are left in target.
  - `soft` — marks removed rows with an `_eds_deleted_at` timestamp.
  - `hard` — calls `delete_missing_rows()` on target to DELETE rows whose PK no longer exists in source.

**Schema fingerprint in state file**
- `DatasetState` gains a `schema_fingerprint: dict[str, str]` field (column → dtype).
- Stored after each run; compared by `_schema_drift` on the next run.
- `schema_fingerprint()` helper in `_state.py` extracts `{col: dtype}` from a DataFrame.

**Updated `eds-loader init` templates**
- All 3 new connectors (oracle, bigquery, elasticsearch) added as target options.
- Generated `loader.yaml` now contains **all** config sections with inline comments:
  Dataset selection, Core behaviour, Incremental options, Reliability, Performance,
  Observability, Data quality, Schema drift, Notifications.
- Header updated with step-by-step workflow comments (Steps 1–6).

### Changed

- `loader.py` — full rewrite to wire in all new hooks: metrics, run-log, notifications, validation, drift, parallel writes, delete mode.
- `config.py` — 10 new fields added to `LoaderConfig`: `batch_size`, `parallelism`, `metrics_file`, `run_log_file`, `on_validation_error`, `rejected_dir`, `schema_drift`, `delete_mode`, `notifications`. ENV-var interpolation added to `from_yaml()`.
- `_state.py` — `DatasetState` gains `schema_fingerprint` field; `load_state()` / `save_state()` updated to persist it; `schema_fingerprint()` helper added.
- `__init__.py` — registers Oracle, BigQuery, Elasticsearch connectors.
- `pyproject.toml` — `bigquery` and `elasticsearch` optional extras added; `[all]` meta-extra updated to include them.
- `cli/_templates.py` — complete rewrite with all new config sections and 3 new target templates.

### New `LoaderConfig` Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `batch_size` | `int \| None` | `None` | Write in row chunks; `None` = unlimited |
| `parallelism` | `int` | `1` | Concurrent dataset writes |
| `metrics_file` | `str \| None` | `None` | Path for JSON metrics; `"auto"` = next to config |
| `run_log_file` | `str \| None` | `None` | Path for JSONL history; `"auto"` = next to config |
| `on_validation_error` | `"warn"\|"fail"\|"quarantine"` | `"warn"` | Row validation policy |
| `rejected_dir` | `str` | `"rejected"` | Dir for quarantined rows |
| `schema_drift` | `"warn"\|"fail"\|"ignore"` | `"warn"` | Schema drift policy |
| `delete_mode` | `"keep"\|"soft"\|"hard"` | `"keep"` | Incremental delete handling |
| `notifications` | `dict[str, list[dict]]` | `{}` | Notification channels by trigger |

### Tests

- 440 unit and integration tests — all passing.
- Existing 396 tests preserved; 44 new tests added for config fields, loader integration, and state management.

---

## [0.3.0] — 2026-08-24

### Added

**Incremental / Delta Load Mode**
- New `load_mode` config field: `"full"` (default, existing behaviour) or
  `"incremental"` (new — hash-based change detection + upsert).
- `eds_loader/_state.py` — state file management module:
  - `dataframe_hash()` — SHA-256 of DataFrame content (stable across runs).
  - `load_state()` / `save_state()` — read/write `.eds_loader_state.json`.
  - State file written atomically (`.tmp` → rename) so a crash cannot
    corrupt it.
- **Skip logic**: datasets whose source content hash is unchanged since the
  last run are skipped entirely — no target I/O performed.
- **Upsert per dialect**:
  - PostgreSQL: `INSERT … ON CONFLICT (pk) DO UPDATE SET …`
  - MySQL: `INSERT … ON DUPLICATE KEY UPDATE …`
  - MSSQL: T-SQL `MERGE … WHEN MATCHED THEN UPDATE … WHEN NOT MATCHED THEN INSERT …`
    (with `fast_executemany`).
  - MongoDB: `collection.replace_one({pk: val}, doc, upsert=True)` — exact
    insert vs update count tracked via `upserted_id`.
  - Datasets with no primary key in `schema.json` fall back to full replace
    (drop + insert) with a logged warning.
- `UpsertResult` dataclass — carries `rows_inserted` + `rows_updated`.
- `Upsertable` protocol — structural protocol for connectors that implement
  `upsert_datasets()`.
- Extended `LoadResult`:
  - `rows_inserted`, `rows_updated` — per-dataset counts in incremental mode.
  - `tables_skipped` — list of datasets skipped due to no change detected.
  - `load_mode` — `"full"` or `"incremental"`.
- New state-aware CLI output for incremental runs: shows CHANGED / SKIPPED
  per dataset with inserted and updated row counts.
- `CREATE TABLE IF NOT EXISTS` in all SQL connectors for upsert path; MSSQL
  uses `IF NOT EXISTS … CREATE TABLE` (T-SQL equivalent).
- `_create_if_not_exists_sql()` — overridable hook in `BaseSQLConnector`.
- `_bulk_upsert()` — overridable hook; MSSQL overrides to set `fast_executemany`.

**Retry on failure**
- New `retry_count` config field (default `0`) — number of extra attempts
  after a `LoadError`.
- New `retry_delay` config field (default `60`) — seconds between attempts.
- Configuration errors (`ConfigError`) are never retried.

**New config fields in `LoaderConfig`**

| Field | Type | Default | Description |
|---|---|---|---|
| `load_mode` | `"full" \| "incremental"` | `"full"` | Load strategy |
| `state_file` | `str \| None` | auto-derived | Path to state JSON |
| `retry_count` | `int` | `0` | Extra retry attempts |
| `retry_delay` | `int` | `60` | Seconds between retries |

### Behaviour Notes

- On the **first** incremental run (no state file) a full upsert is performed
  for all datasets and the state file is created on success.
- If a run fails mid-way, the state file is **not updated** — the next run
  will re-process all datasets that were not successfully upserted.
- Deleted rows are **kept** in the target (incremental mode only inserts and
  updates — it does not delete).

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
