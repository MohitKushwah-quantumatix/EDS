# PADR-003: Output Adapter Isolation

**Status:** Accepted (P001), revised (P001.1)

## Context

Parquet is the only output format today, and SQL Server, PostgreSQL, MongoDB
and Kafka are all plausible later. If business code learns about Parquet, each
of those becomes a change to business code.

## Decision

No business generator may import an adapter, and no adapter may import a
generator. They meet only at `polars.DataFrame` and at two protocols in
`eds.adapters.base`:

* `DatasetWriter.write(datasets) -> tuple[WriteResult, ...]`
* `DatasetReader.read(names) -> dict[str, DataFrame]`

**The destination is bound at construction, not passed per call.** P001
declared `write(datasets, destination: Path)`, which is a file system leaking
into the contract: a SQL adapter has a connection and a schema, Kafka has
brokers and a topic, REST has a base URL. None is a `Path`. The P001 return
type `tuple[Path, ...]` had the same problem — meaningless for a table or a
topic.

`WriteResult(dataset, location: str, rows: int)` replaces it. Every
conceivable adapter can answer what it wrote, where it landed as an opaque
identifier, and how many rows.

Adapter failures surface as `AdapterError` rather than a storage-specific
exception, so a caller need not know which adapter it is talking to in order to
handle a failure.

## Consequences

**Good.** A SQL adapter is a new package implementing two methods. Nothing in
`eds/domains/` changes.

**Cost.** The protocol is narrow — write frames, read frames — and a future
adapter with genuinely different needs (streaming, transactions, upserts) will
need it widened. Widening a protocol with one implementation and one real
consumer is cheap; guessing at those needs now is not.

**Deliberately not done.** The existing Parquet reader and writer were not
rewritten. `ParquetAdapter` wraps them, and the CLI still calls the functions
directly. The write path that produced every dataset to date is untouched,
which is what let P001 prove byte-identical output.

**Enforcement.** `test_no_domain_generator_knows_about_an_output_format` scans
`eds/domains/` for imports of any storage technology, and the layering test
forbids `eds.adapters` imports from `eds/domains/` outright.
