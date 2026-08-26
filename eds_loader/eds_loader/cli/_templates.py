"""Starter YAML config templates for ``eds-loader init``.

Each key in :data:`SOURCE_TEMPLATES` / :data:`TARGET_TEMPLATES` is a
connector ``kind``.  The value is a YAML snippet (without a top-level
``source:`` / ``target:`` wrapper) with every config field present,
required ones un-commented and optional ones commented out with a note.

:func:`build_config` assembles a complete ``loader.yaml`` string from
one source template and one target template.
"""

from __future__ import annotations

__all__ = ["SOURCE_TEMPLATES", "TARGET_TEMPLATES", "build_config", "KNOWN_KINDS"]

# ---------------------------------------------------------------------------
# Source templates
# ---------------------------------------------------------------------------

SOURCE_TEMPLATES: dict[str, str] = {
    "local_fs": """\
source:
  kind: local_fs
  path: ./output          # required -- directory containing dataset files + schema.json
  # format: parquet       # optional -- parquet (default) | csv | json | ndjson | excel | avro | orc
""",

    "remote_fs": """\
source:
  kind: remote_fs
  host: sftp.example.com  # required
  username: eds_user       # required
  remote_path: /data/eds  # required -- remote directory containing dataset files + schema.json
  port: 22                 # optional -- default: 22
  # password_env: SFTP_PASSWORD   # env-var holding the password (preferred)
  # password: ""                  # inline password (not recommended for production)
  # key_filename: ~/.ssh/id_rsa   # path to private key file
  # format: parquet               # optional -- parquet (default) | csv | json | ndjson | excel | avro | orc
""",

    "s3": """\
source:
  kind: s3
  bucket: my-eds-bucket   # required
  # prefix: datasets/2024/        # optional -- prefix within the bucket
  aws_access_key_id: AKIAIOSFODNN7EXAMPLE  # optional -- omit to use AWS credential chain
  aws_secret_access_key_env: AWS_SECRET_ACCESS_KEY  # env-var for secret key
  # region: us-east-1             # optional -- default: us-east-1
  # endpoint_url:                 # optional -- for MinIO / LocalStack
  # format: parquet               # optional -- parquet (default) | csv | json | ndjson | excel | avro | orc
""",

    "azure_blob": """\
source:
  kind: azure_blob
  account_name: myaccount  # required
  container: eds-data       # required
  # prefix: datasets/2024/        # optional -- prefix within the container
  account_key_env: AZURE_STORAGE_KEY  # env-var for storage account key
  # connection_string_env: AZURE_STORAGE_CONN_STR  # alternative: full connection string
  # format: parquet               # optional -- parquet (default) | csv | json | ndjson | excel | avro | orc
""",

    "gcs": """\
source:
  kind: gcs
  bucket: my-eds-bucket   # required
  # prefix: datasets/2024/        # optional -- prefix within the bucket
  # credentials_env: GOOGLE_APPLICATION_CREDENTIALS  # path to service account JSON
  # credentials_file: /path/to/sa.json               # explicit credentials file
  # project: my-gcp-project       # optional -- GCP project ID
  # format: parquet               # optional -- parquet (default) | csv | json | ndjson | excel | avro | orc
""",
}

# ---------------------------------------------------------------------------
# Target templates
# ---------------------------------------------------------------------------

TARGET_TEMPLATES: dict[str, str] = {
    "local_fs": """\
target:
  kind: local_fs
  path: ./landing         # required -- directory to write .parquet + schema.json
""",

    "remote_fs": """\
target:
  kind: remote_fs
  host: sftp.example.com  # required
  username: eds_user       # required
  remote_path: /landing/eds  # required -- remote directory to write into
  port: 22                 # optional -- default: 22
  # password_env: SFTP_PASSWORD
  # key_filename: ~/.ssh/id_rsa
""",

    "s3": """\
target:
  kind: s3
  bucket: my-landing-bucket  # required
  # prefix: landing/2024/        # optional
  aws_access_key_id: AKIAIOSFODNN7EXAMPLE
  aws_secret_access_key_env: AWS_SECRET_ACCESS_KEY
  # region: us-east-1
""",

    "azure_blob": """\
target:
  kind: azure_blob
  account_name: myaccount  # required
  container: eds-landing    # required
  # prefix: landing/2024/        # optional
  account_key_env: AZURE_STORAGE_KEY
""",

    "gcs": """\
target:
  kind: gcs
  bucket: my-landing-bucket  # required
  # prefix: landing/2024/        # optional
  # credentials_env: GOOGLE_APPLICATION_CREDENTIALS
""",

    "postgres": """\
target:
  kind: postgres
  host: localhost           # required
  database: eds_db          # required
  user: eds_loader          # required
  password_env: EDS_PG_PASSWORD  # env-var holding the password (preferred)
  # password: ""                 # inline password (not recommended for production)
  port: 5432                # optional -- default: 5432
  schema: public            # optional -- default: public
""",

    "mysql": """\
target:
  kind: mysql
  host: localhost           # required
  database: eds_db          # required
  user: eds_loader          # required
  password_env: EDS_MYSQL_PASSWORD
  # password: ""
  port: 3306                # optional -- default: 3306
""",

    "mssql": """\
target:
  kind: mssql
  host: localhost           # required
  database: eds_db          # required
  user: eds_loader          # required
  password_env: EDS_MSSQL_PASSWORD  # env-var holding the password (preferred)
  # password: ""                    # inline password (not recommended for production)
  port: 1433                # optional -- default: 1433
  schema: dbo               # optional -- default: dbo
  driver: "ODBC Driver 17 for SQL Server"  # optional -- must match an installed ODBC driver
  # encrypt: true                   # optional -- default: true
  # trust_server_certificate: false # optional -- set true for self-signed certs (dev only)
""",

    "mongodb": """\
target:
  kind: mongodb
  host: localhost           # required
  database: eds_db          # required
  # username: eds_loader          # optional -- omit for unauthenticated connections
  # password_env: EDS_MONGO_PASSWORD
  port: 27017               # optional -- default: 27017
  # auth_source: admin            # optional -- authentication database, default: admin
""",

    "oracle": """\
target:
  kind: oracle
  host: oracle.example.com  # required
  database: ORCLPDB1        # required -- Oracle service name or SID
  user: eds_loader          # required
  password_env: EDS_ORACLE_PASSWORD  # env-var holding the password (preferred)
  # password: ""                      # inline password (not recommended for production)
  port: 1521                # optional -- default: 1521
  # schema: EDS_DATA               # optional -- defaults to username (uppercase)
  # mode: thin                     # optional -- thin (default, no client) | thick
  # Install: pip install eds-loader[oracle]
""",

    "bigquery": """\
target:
  kind: bigquery
  project: my-gcp-project   # required -- GCP project ID
  dataset: eds_data          # required -- BigQuery dataset name
  # credentials_file: /path/to/service-account.json  # optional -- omit for ADC
  # location: US              # optional -- dataset location, default: US
  # create_dataset: true      # optional -- create BQ dataset if missing, default: true
  # Install: pip install eds-loader[bigquery]
""",

    "elasticsearch": """\
target:
  kind: elasticsearch
  host: http://localhost:9200  # required -- Elasticsearch / OpenSearch URL
  index_prefix: eds_            # optional -- prepended to every index name, default: eds_
  # username: elastic            # optional -- HTTP Basic auth username
  # password_env: ES_PASSWORD    # optional -- env-var for password
  # verify_certs: true           # optional -- verify TLS certificates, default: true
  # timeout: 30                  # optional -- request timeout seconds, default: 30
  # shards: 1                    # optional -- primary shards per index, default: 1
  # replicas: 0                  # optional -- replicas per index, default: 0
  # Install: pip install eds-loader[elasticsearch]
""",
}

# ---------------------------------------------------------------------------
# Shared footer — appended to every generated config
# ---------------------------------------------------------------------------

_FOOTER = """\
# ---------------------------------------------------------------------------
# Dataset selection
# ---------------------------------------------------------------------------
tables: []                  # empty = load every dataset in schema.json
                            # or specify a subset: [customers, orders, products]

# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------
enforce_constraints: true   # apply PK / FK / UNIQUE constraints on the target (where supported)
schema_required: true       # set to false if there is no schema.json at the source
                            # (datasets will be auto-discovered from *.parquet files)

# Load mode: full (default) = complete replace every run.
# incremental = hash-based change detection; only upsert changed datasets.
load_mode: full             # full | incremental

# ---------------------------------------------------------------------------
# Incremental load options (only used when load_mode: incremental)
# ---------------------------------------------------------------------------
# state_file: .loader_state.json   # where to save the change-detection state
# delete_mode: keep                # keep | soft | hard
#   keep  -- deleted source rows stay in target (default)
#   soft  -- add _eds_deleted_at timestamp to removed rows
#   hard  -- DELETE rows from target that no longer exist in source

# ---------------------------------------------------------------------------
# Reliability
# ---------------------------------------------------------------------------
retry_count: 0              # extra retry attempts after a load failure (0 = no retries)
retry_delay: 60             # seconds to wait between retries

# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------
parallelism: 1              # number of datasets to load concurrently (default: 1 = sequential)
                            # increase for independent datasets with no FK dependencies
# batch_size: 100000        # write in chunks of N rows (default: unlimited)
                            # useful for very large datasets to limit peak memory

# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------
# metrics_file: auto        # write run_metrics.json after every run
                            # "auto" = next to this config file | or specify a full path
# run_log_file: auto        # append to JSONL run history file (used by: eds-loader history)
                            # "auto" = .eds_loader_runs.jsonl next to this file

# ---------------------------------------------------------------------------
# Data quality — row-level validation
# ---------------------------------------------------------------------------
# on_validation_error: warn # warn (default) | fail | quarantine
#   warn       -- log violations, load all rows anyway
#   fail       -- abort the run if any row fails validation
#   quarantine -- load valid rows; write rejected rows to rejected_dir
# rejected_dir: rejected    # directory for quarantined rows (default: ./rejected)
#
# Validation rules are declared in schema.json per dataset:
#   "validation": {
#     "patient_id": {"not_null": true},
#     "age":        {"min": 0, "max": 150},
#     "gender":     {"allowed_values": ["M", "F", "Other"]},
#     "email":      {"regex": "^[\\\\w.+-]+@[\\\\w-]+\\\\.[\\\\w.]+$"}
#   }

# ---------------------------------------------------------------------------
# Schema drift detection
# ---------------------------------------------------------------------------
# schema_drift: warn        # warn (default) | fail | ignore
#   warn   -- log column additions / removals / type changes, continue
#   fail   -- abort the run if the source schema changed since the last run
#   ignore -- silent

# ---------------------------------------------------------------------------
# Notifications (email / Slack / Teams / webhook)
# ---------------------------------------------------------------------------
# notifications:
#   on_failure:
#     - kind: email
#       smtp_host: smtp.gmail.com
#       smtp_port: 587
#       from_addr: eds-loader@company.com
#       to: [data-team@company.com]
#       password_env: SMTP_PASSWORD
#     - kind: slack
#       webhook_url_env: SLACK_WEBHOOK_URL
#     - kind: teams
#       webhook_url_env: TEAMS_WEBHOOK_URL
#   on_success:
#     - kind: webhook
#       url: https://monitoring.company.com/api/runs
#   always:
#     - kind: webhook
#       url: https://audit.company.com/api/events

# ---------------------------------------------------------------------------
# Schedule — when to run automatically (optional)
# ---------------------------------------------------------------------------
# Fill in this block and run: eds-loader schedule -c <this-file>
# to register the scheduled task on Windows Task Scheduler or Linux crontab.
#
# style 1: simple (no cron knowledge needed)
# schedule:
#   time: "02:00"              # HH:MM in 24-hour format
#   timezone: Asia/Kolkata     # IANA timezone name
#   frequency: daily           # daily | every_other_day | weekly | monthly
#   # on_day: Monday           # required when frequency: weekly
#   # on_date: 1               # required when frequency: monthly (1-28)
#
# style 2: full cron expression (advanced)
# schedule:
#   cron: "0 2 * * *"          # 5-field cron expression
#   timezone: Asia/Kolkata
#
# date range (optional — omit to run indefinitely)
#   start_date: "2026-09-01"   # YYYY-MM-DD — do not run before this date
#   end_date:   "2026-12-31"   # YYYY-MM-DD — stop running after this date
#
# skip rules (optional)
#   skip_weekends: true        # skip Saturday and Sunday
#   skip_days:                 # skip specific weekdays
#     - Saturday
#     - Sunday
#   skip_dates:                # skip specific calendar dates (holidays)
#     - "2026-10-02"
#     - "2026-10-24"
#
# retry if the run fails (optional)
#   retry_on_failure: true
#   retry_after_minutes: 30
#   max_retries: 2
"""

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

KNOWN_KINDS: set[str] = set(SOURCE_TEMPLATES) | set(TARGET_TEMPLATES)


def build_config(source_kind: str, target_kind: str) -> str:
    """Build a complete starter ``loader.yaml`` string.

    Args:
        source_kind: Connector kind for the source section.
        target_kind: Connector kind for the target section.

    Returns:
        A YAML string ready to write to disk.  Contains every supported
        field — required ones uncommented, optional ones commented out
        with descriptive notes.

    Raises:
        ValueError: If *source_kind* or *target_kind* is not recognised.
    """
    if source_kind not in SOURCE_TEMPLATES:
        known = ", ".join(sorted(SOURCE_TEMPLATES))
        raise ValueError(
            f"Unknown source kind {source_kind!r}. Known source kinds: {known}"
        )
    if target_kind not in TARGET_TEMPLATES:
        known = ", ".join(sorted(TARGET_TEMPLATES))
        raise ValueError(
            f"Unknown target kind {target_kind!r}. Known target kinds: {known}"
        )

    header = (
        "# EDS Loader configuration — generated by 'eds-loader init'\n"
        f"# Source: {source_kind}  →  Target: {target_kind}\n"
        "#\n"
        "# Steps:\n"
        "#   1. Fill in all required fields (un-commented).\n"
        "#   2. Uncomment and adjust optional fields as needed.\n"
        "#   3. Validate:  eds-loader validate -c <this-file>\n"
        "#   4. Run:       eds-loader run      -c <this-file>\n"
        "#   5. Status:    eds-loader status   -c <this-file>\n"
        "#   6. History:   eds-loader history  -c <this-file>\n"
        "#\n\n"
    )
    return (
        header
        + SOURCE_TEMPLATES[source_kind]
        + "\n"
        + TARGET_TEMPLATES[target_kind]
        + "\n"
        + _FOOTER
    )
