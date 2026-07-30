"""Referential integrity checks bound to the Retail dataset declarations.

The checks themselves are domain independent and live in
:mod:`eds.core.validation.referential`. This module supplies the one thing the
framework cannot know: which declarations to check when the caller does not
say. That default is the F001 master datasets, which is what
:func:`eds.domains.retail.validation.master_data.validate_master_data` relies
on.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import polars as pl

from eds.core.schema import Dataset
from eds.core.validation.issues import ValidationIssue
from eds.core.validation.referential import (
    validate_foreign_keys,
    validate_primary_key,
    validate_schema,
)
from eds.core.validation.referential import (
    validate_referential_integrity as _validate_referential_integrity,
)
from eds.domains.retail.domain.master_data import MASTER_DATA_DATASETS

__all__ = [
    "validate_foreign_keys",
    "validate_primary_key",
    "validate_referential_integrity",
    "validate_schema",
]


def validate_referential_integrity(
    datasets: Mapping[str, pl.DataFrame],
    declarations: Sequence[Dataset] = MASTER_DATA_DATASETS,
) -> list[ValidationIssue]:
    """Run every schema, key, and foreign key check over a set of datasets.

    Args:
        datasets: Generated datasets, keyed by name. This may contain more
            datasets than are being checked, so that foreign keys pointing at
            another feature's output still resolve.
        declarations: The dataset declarations to check. Defaults to the F001
            master datasets; every later feature passes its own.

    Returns:
        Every issue found, in dataset declaration order. Empty means the data
        is referentially sound.
    """
    return _validate_referential_integrity(datasets, declarations)
