"""PostgreSQL DDL derived from :class:`eds.core.schema.Dataset`.

PADR-018 originally left constraint enforcement out of scope: tables were
created from Polars' inferred schema, so a Postgres target held the same
rows as the store of record but none of its declared primary keys, foreign
keys, or uniqueness rules. This module closes that gap -- but stays under
``eds.adapters``, so it may only import ``eds.core`` (PADR-003: "adapters and
domains are siblings that must not know about each other"). It has no idea
what a "customer" or an "order" is; it only knows how to turn a
:class:`~eds.core.schema.Dataset` -- a plain, domain-agnostic declaration --
into a ``CREATE TABLE`` statement.

**Where the Retail dataset declarations actually come from** is
``eds.runners.retail``, the one package allowed to import both
``eds.domains`` and ``eds.adapters`` (PADR-014, PADR-015). A caller who wants
constraints enforced passes a ``name -> Dataset`` mapping into
:func:`~eds.adapters.postgres.writer.write_datasets`; this module never goes
looking for one itself.

**Write order is computed from the FK graph you hand it**, not from a
hardcoded domain order: :func:`write_order` topologically sorts whatever
``Dataset`` objects it is given by their own declared foreign keys. A
self-referencing foreign key (``categories`` is the one case in the Retail
schema) is not an ordering constraint between two different tables, so it is
ignored for sorting purposes and left for
:func:`create_table_statement` to express inline, which PostgreSQL allows
within a single ``CREATE TABLE``.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from eds.core.schema import Dataset

__all__ = ["create_table_statement", "write_order"]

# Polars dtypes actually used across the Retail datasets. A dtype outside
# this map falls back to TEXT rather than raising, so a future column type
# doesn't hard-fail constrained writes.
_POSTGRES_TYPE: dict[type, str] = {
    pl.Int64: "BIGINT",
    pl.Float64: "DOUBLE PRECISION",
    pl.Boolean: "BOOLEAN",
    pl.String: "TEXT",
    pl.Date: "DATE",
    pl.Datetime: "TIMESTAMP",
}


def _column_type(dtype: pl.DataType) -> str:
    """Map a Polars dtype to a PostgreSQL column type.

    Args:
        dtype: The column's declared Polars dtype.

    Returns:
        The PostgreSQL type name. Falls back to ``TEXT`` for any dtype not
        in the map, which keeps a future column loadable rather than
        failing DDL generation outright.
    """
    return _POSTGRES_TYPE.get(dtype.base_type(), "TEXT")


def create_table_statement(dataset: Dataset, *, schema: str) -> str:
    """Build a ``CREATE TABLE`` statement for one dataset.

    Includes the primary key, every declared foreign key, and every declared
    uniqueness constraint. A self-referencing foreign key is valid
    PostgreSQL within the same ``CREATE TABLE`` statement, since the table
    name is registered before its constraints are checked.

    Args:
        dataset: The dataset to build a table for.
        schema: The PostgreSQL schema the table belongs to.

    Returns:
        A complete, semicolon-terminated ``CREATE TABLE`` statement.
    """
    lines = [f'  "{name}" {_column_type(dtype)}' for name, dtype in dataset.columns.items()]
    lines.append(f'  PRIMARY KEY ("{dataset.primary_key}")')

    for unique_column in dataset.unique_columns:
        lines.append(f'  UNIQUE ("{unique_column}")')

    for fk in dataset.foreign_keys:
        lines.append(
            f'  FOREIGN KEY ("{fk.column}") REFERENCES "{schema}"."{fk.references}" ("{fk.referenced_column}")'
        )

    body = ",\n".join(lines)
    return f'CREATE TABLE "{schema}"."{dataset.name}" (\n{body}\n);'


def write_order(datasets: Mapping[str, Dataset]) -> list[str]:
    """Sort dataset names so every table is created after what it references.

    A topological sort over the foreign keys declared *within* ``datasets``
    itself -- there is no external ordering to consult, by design (see
    module docstring). A foreign key pointing outside ``datasets`` is
    assumed to reference a table that already exists and is not an ordering
    constraint here. A self-reference is dropped rather than treated as a
    cycle, since PostgreSQL accepts it inline.

    Args:
        datasets: Dataset name to declaration, in any order.

    Returns:
        The same names, ordered so that a dataset never precedes one of its
        own non-self foreign key targets. Names not present as keys are
        never referenced as edges even if some other dataset's foreign key
        names them (they are simply assumed to exist already).

    Raises:
        ValueError: If the foreign keys among ``datasets`` form a cycle
            spanning two or more tables, which cannot be expressed as a
            sequence of ``CREATE TABLE`` statements.
    """
    remaining = dict(datasets)
    ordered: list[str] = []
    while remaining:
        ready = [
            name
            for name, dataset in remaining.items()
            if all(fk.references == name or fk.references not in remaining for fk in dataset.foreign_keys)
        ]
        if not ready:
            raise ValueError(f"Foreign keys among {sorted(remaining)} form a cycle; cannot order the writes.")
        ordered.extend(sorted(ready))
        for name in ready:
            del remaining[name]
    return ordered
