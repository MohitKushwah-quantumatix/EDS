# =============================================================================
# EDS Generator — Dockerfile
# =============================================================================
# Builds a self-contained image that runs EDS simulation (retail or healthcare)
# and writes Parquet output to a mounted volume.
#
# BUILD (from EDS/ root):
#   docker build -t eds-generator:latest -f docker/eds-generator/Dockerfile EDS/
#
# ── Quick run (one day, CLI args) ────────────────────────────────────────────
#   docker run --rm \
#     -v ./my-shop:/app/my-shop \
#     eds-generator:latest \
#     python run_day.py --domain retail --date 2026-01-01
#
# ── Config-driven run (generate.yaml) ────────────────────────────────────────
#   docker run --rm \
#     -v ./generate.yaml:/config/generate.yaml \
#     -v ./my-hospital:/app/my-hospital \
#     eds-generator:latest \
#     python generate.py --config /config/generate.yaml
#
# ── Config-driven run with custom domain configs ──────────────────────────────
#   docker run --rm \
#     -v ./generate.yaml:/config/generate.yaml \
#     -v ./my-configs:/config/domain-configs \
#     -v ./my-hospital:/app/my-hospital \
#     eds-generator:latest \
#     python generate.py --config /config/generate.yaml
# =============================================================================

# ── Base image ────────────────────────────────────────────────────────────────
FROM python:3.12-slim

# ── System packages ───────────────────────────────────────────────────────────
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR /app

# ── Install ALL dependencies (cached layer — re-runs only if deps change) ─────
# Install deps directly to avoid hatchling needing the full source tree
# (version.py + LICENSE) before the source is copied.
RUN pip install --no-cache-dir \
    "polars>=1.0" \
    "pydantic>=2.7" \
    "faker>=25.0" \
    "typer>=0.12" \
    "pyyaml>=6.0" \
    "sqlalchemy>=2.0" \
    "pandas>=2.0" \
    "pyarrow>=14.0"

# ── Copy full source tree ─────────────────────────────────────────────────────
# Now copy everything. This layer re-runs when source changes,
# but the pip install layer above is already cached.
COPY . .

# ── Install the eds package itself (no deps re-install) ───────────────────────
RUN pip install --no-cache-dir --no-deps .

# ── Create config mount points ────────────────────────────────────────────────
# /config          → mount generate.yaml and/or domain config overrides here
# /config/domain-configs → mount custom retail/ or healthcare/ yaml files here
RUN mkdir -p /config/domain-configs

# ── Default command ───────────────────────────────────────────────────────────
# To use generate.yaml:
#   docker run ... eds-generator:latest python generate.py --config /config/generate.yaml
# To use CLI directly:
#   docker run ... eds-generator:latest python run_day.py --domain retail --date 2026-01-01
CMD ["python", "generate.py", "--help"]
