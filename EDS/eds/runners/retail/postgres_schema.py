"""Deprecated alias for :mod:`eds.runners.retail.dataset_registry`.

``RETAIL_DATASET_SCHEMAS`` moved here first, back when the only consumer
was the PostgreSQL adapter. It now also backs ``schema.json`` export
(:mod:`eds.core.schema_export`), which has nothing to do with PostgreSQL, so
the registry itself lives in :mod:`eds.runners.retail.dataset_registry`.
This module re-exports the same object under its original name so existing
imports keep working.
"""

from __future__ import annotations

from eds.runners.retail.dataset_registry import RETAIL_DATASET_SCHEMAS

__all__ = ["RETAIL_DATASET_SCHEMAS"]
