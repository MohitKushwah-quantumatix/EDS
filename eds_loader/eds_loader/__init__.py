"""EDS Loader — move EDS-generated data from any source to any target.

Quickstart::

    from eds_loader import load
    from eds_loader.config import LoaderConfig
    from pathlib import Path

    config = LoaderConfig.from_yaml(Path("loader.yaml"))
    result = load(config)
    print(f"{result.total_rows:,} rows written")

Or from the command line::

    eds-loader run --config loader.yaml
    eds-loader connectors
"""

from __future__ import annotations

from eds_loader.loader import LoadResult, load
from eds_loader.version import __version__

# Import connector modules to trigger self-registration.
# Each connector calls register_connector() at module level when imported.
# Add one line here for every new connector added in Steps 3–9.
import eds_loader.connectors.local_fs             # noqa: F401
import eds_loader.connectors.remote_fs            # noqa: F401
import eds_loader.connectors.postgres             # noqa: F401
import eds_loader.connectors.mysql                # noqa: F401
import eds_loader.connectors.mssql                # noqa: F401
import eds_loader.connectors.mongodb              # noqa: F401
import eds_loader.connectors.s3                   # noqa: F401
import eds_loader.connectors.azure_blob           # noqa: F401
import eds_loader.connectors.gcs                  # noqa: F401
import eds_loader.connectors.oracle               # noqa: F401
import eds_loader.connectors.bigquery             # noqa: F401
import eds_loader.connectors.elasticsearch_connector  # noqa: F401

__all__ = ["load", "LoadResult", "__version__"]
