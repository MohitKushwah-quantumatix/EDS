"""Output adapters.

An adapter is the only place that knows how generated data is persisted. No
business generator imports an adapter, and no adapter imports a generator
(PADR-003): both meet at the :class:`~eds.adapters.base.DatasetWriter` and
:class:`~eds.adapters.base.DatasetReader` protocols.

Parquet (``eds.adapters.parquet``), PostgreSQL (``eds.adapters.postgres``),
and SQLite in-memory (``eds.adapters.sqlite``) are implemented today.
"""
