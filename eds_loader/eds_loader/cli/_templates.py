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
}

# ---------------------------------------------------------------------------
# Footer (appended to every generated config)
# ---------------------------------------------------------------------------

_FOOTER = """\
# Optional loader settings
tables: []                  # empty = load every dataset in schema.json
                            # or specify a subset: [customers, orders]
enforce_constraints: true   # set to false to skip PK/FK/UNIQUE enforcement
schema_required: true       # set to false if there is no schema.json at the source
                            # (datasets will be auto-discovered from *.parquet files)
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
        A YAML string ready to write to disk.

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
        "# Fill in all required fields and then validate with:\n"
        "#   eds-loader validate -c <this-file>\n\n"
    )
    return (
        header
        + SOURCE_TEMPLATES[source_kind]
        + "\n"
        + TARGET_TEMPLATES[target_kind]
        + "\n"
        + _FOOTER
    )
