# =============================================================================
# EDS Loader — Dockerfile
# =============================================================================
# Builds a self-contained image that runs eds-loader against any source/target
# pair defined by a mounted loader.yaml config file.
#
# BUILD (from EDS/ root):
#   docker build -t eds-loader:latest -f docker/eds-loader/Dockerfile eds_loader/
#
# RUN:
#   docker run --rm \
#     -v ./loader.yaml:/config/loader.yaml \
#     -v ./logs:/app/logs \
#     eds-loader:latest run -c /config/loader.yaml
# =============================================================================

# ── Base image ────────────────────────────────────────────────────────────────
FROM python:3.12-slim

# ── System packages ───────────────────────────────────────────────────────────
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*
# libpq-dev: needed by psycopg (PostgreSQL driver) to compile C extension

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR /app

# ── Install ALL dependencies (cached layer — re-runs only if deps change) ─────
# We install deps directly by name instead of via pip install .[all],
# because hatchling requires the full source tree to build the package wheel.
# Installing deps first and the package second gives us optimal layer caching.
RUN pip install --no-cache-dir \
    "polars>=1.0" \
    "pydantic>=2.7" \
    "typer>=0.12" \
    "pyyaml>=6.0" \
    "psycopg[binary]>=3.1" \
    "pymysql>=1.1" \
    "pyodbc>=5.0" \
    "pymongo>=4.6" \
    "boto3>=1.34" \
    "azure-storage-blob>=12.19" \
    "google-cloud-storage>=2.14" \
    "paramiko>=3.4" \
    "tzdata"

# ── Copy full source tree ─────────────────────────────────────────────────────
# Now copy everything (pyproject.toml, LICENSE, version.py, source code).
# This layer rebuilds when source changes, but pip deps above are already cached.
COPY . .

# ── Install the eds-loader package itself (no deps re-install) ───────────────
RUN pip install --no-cache-dir --no-deps .

# ── Create mount points ───────────────────────────────────────────────────────
RUN mkdir -p /config /app/logs /app/rejected

# ── Runtime entrypoint ────────────────────────────────────────────────────────
# eds-loader is installed as a CLI command by pip (see pyproject.toml scripts).
ENTRYPOINT ["eds-loader"]

# Default: show help when run with no arguments.
CMD ["--help"]
