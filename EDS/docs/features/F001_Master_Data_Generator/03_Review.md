# F001 - Review

| Field | Value |
| --- | --- |
| Outcome | Implemented under stated assumptions |
| Environment | Windows 10, Python 3.13.0 |
| Verified | `pytest`, `ruff check .`, `ruff format --check .`, `mypy eds`, end-to-end CLI run |

## Verification

| Gate | Result |
| --- | --- |
| `pytest` | Pass - 262 passed |
| `ruff check .` | Pass - all checks passed |
| `ruff format --check .` | Pass |
| `mypy eds` | Pass - no issues in 80 source files |
| `eds generate master-data` | Exit 0 - 13 Parquet files, 4,597 rows, validation passed |

## Success criteria

| Criterion | Evidence |
| --- | --- |
| All master datasets generated | 13 of 13 datasets, none empty |
| Referential integrity maintained | `validate_referential_integrity` over declared FK edges; clean on generated data |
| No orphan records | `orphan_reference` rule; failure path covered by an injected-defect test |
| Deterministic for the same seed | Frame-equality tests at generator, orchestrator, and CLI levels |
| Parquet files exported | Round-trip tests assert schema and row counts survive |
| Data validated without errors | `validate_master_data` returns zero issues |

## Architecture

```
config  ->  generators  ->  MasterData bundle  ->  validation  ->  parquet
```

Master data is carried as **Polars DataFrames**, not one object per row. The
scalability principle (up to 100 million products) rules out instantiating a
Pydantic model per product. Pydantic is used where it earns its cost - on
configuration, where a bad value should fail before a long run starts.

Schemas are declared once in `eds/domain/*/schema.py` as `Dataset` objects
carrying columns, primary key, unique columns, and foreign key edges.
Generators, validators, and the exporter all read those declarations, so
adding a column or an FK is a one-line change rather than an edit in four
places.

### Determinism

Each generator draws from a **named stream** seeded with
`sha256(f"{seed}:{stream}")` rather than sharing one RNG. Two consequences:

- Resizing or adding a dataset does not shift the values of any other.
- `hash()` is not used, so output is stable across processes and versions.

Reference data (countries, states, the commercial catalogues) is
seed-independent by design: real ISO codes and a retailer's payment methods
are facts, not samples. Only synthesised attributes vary with the seed.

## Assumptions made

Each is a decision the business context did not make.

1. **Identifiers are sequential 64-bit integers** per dataset, starting at 1,
   with human-readable business codes alongside (`SKU-00000001`, `WH-0001`).
   Warehouse and dimension keys stay small and join cheaply in every target
   engine.
2. **Postal codes are a column on `cities`**, not a fourteenth dataset - the
   output list names thirteen files.
3. **System reference values** (currency, unit of measure, product status,
   warehouse status) are `StrEnum` members written as string columns, not
   separate lookup tables. The output list names no such files.
4. **Business configuration lives in `configs/master_data.yaml`**, separate
   from platform settings in `simulation.yaml`. F000 established that
   `configs/` holds platform configuration; this file is the business
   counterpart.
5. **Geography is real, cities are synthesised.** Six countries with genuine
   ISO codes and subdivisions (US, CA, GB, DE, AU, IN) form a fixed backbone.
   Cities are generated on top, with coordinates inside the country's
   bounding box and postal codes in the country's format. A configured
   country without reference data raises rather than inventing one.
6. **Prices are sampled log-uniformly** within a per-category band, then
   rounded to retail endings. Uniform sampling would put as many $2,000
   televisions in the catalog as $200 ones and distort every revenue metric
   downstream. Cost is derived from a margin band so `unit_cost < list_price`
   holds by construction.
7. **Products attach only to leaf categories**, and the price band comes from
   the leaf's level-1 ancestor.
8. **Inventory is a sample, not a cross product.** Each product is stocked in
   `warehouses_per_product` warehouses, so row count is
   `product_count * warehouses_per_product` rather than
   `product_count * warehouse_count`. Only active or under-maintenance
   warehouses hold stock.
9. **Currency follows the first configured country**, so a UK-only run prices
   in GBP.
10. **Tax codes are generated per country** and prefixed with the country code
    to stay unique; other commercial tables are single global catalogues.
11. **New domain packages** `geography`, `supply_chain`, and `commercial` were
    added under `eds/domain/`. The F000 tree has no home for countries,
    suppliers, or tax codes; these follow the existing one-package-per-context
    pattern.
12. **`eds/config.py` and `eds/domain/master_data.py`** are new top-level
    modules. The F000 tree has no configuration module, and the dataset
    registry needs a single home that generators, validators, and exporters
    can all import.

## Known limitation: the 100 million product ceiling

The design principle asks for 100 products to 100 million without code
changes. **This is not met in full, and the gap is deliberate rather than
overlooked.**

What is in place: `iter_product_batches` and `iter_inventory_batches` yield
fixed-size frames, and a test asserts batch size does not change the output.
The generation path is therefore already incremental.

What is missing: `generate_products` concatenates those batches in memory,
because Polars writes a Parquet file in one call and appending row groups
needs a writer that is not among the approved dependencies. At roughly 300
bytes per product row, 100 million products is about 30 GB - beyond a single
machine's memory.

The practical ceiling is in the low tens of millions. Closing the gap needs
either a streaming Parquet writer or partitioned output
(`products/part-0000.parquet`), which changes the output contract and is a
decision for the feature owner. It is listed under improvements rather than
implemented.

## Test coverage

262 tests, every module carrying success and failure paths.

| Area | Tests | Notable failure paths |
| --- | --- | --- |
| Package layout (F000) | 63 | Undeclared subpackage import raises |
| Configuration | 30 | Empty country list, warehouses exceeding count, unknown key, malformed YAML, missing file |
| Random streams | 10 | Empty stream name rejected |
| Frames and registry | 17 | Missing, unexpected, and ragged columns; negative code numbers |
| Geography | 16 | Unknown country lists supported codes |
| Commercial | 13 | Percentage discounts bounded, transit windows coherent |
| Catalog | 22 | Inverted price band, 100% margin, every empty upstream dataset |
| Supply chain and inventory | 17 | Empty cities, all-warehouses-closed |
| Orchestrator | 15 | Unknown country aborts; null seed replays from reported seed |
| Validation | 26 | Every rule proved by injecting the defect it detects |
| Parquet exporter | 8 | Output path occupied by a file |
| CLI | 13 | Bad config dir (exit 2), invalid override (exit 2), sub-minimum count |
| Version and CLI (F000) | 11 | Unknown command and option exit non-zero |

The validation tests are the load-bearing ones: each corrupts a valid bundle
and asserts the specific rule fires, so they prove the validators catch real
defects rather than passing on clean data.

## Defects found and fixed during implementation

1. `generate_cities` called a `MasterDataConfig` method that does not exist -
   locale belongs to `PlatformConfig`. Now an explicit parameter.
2. `build_frame(DATASET, {})` was used as an empty-frame fallback, which the
   column check correctly rejects. Replaced with `empty_frame`.
3. A product-weight helper was public and defined after its use. Made private
   and moved.
4. `_COMPRESSION` typed as `str` failed against the Parquet writer's literal
   type. Narrowed to `Literal["snappy"]`.

## Improvements not implemented

- Streaming or partitioned Parquet output to lift the product ceiling.
- Country-specific tax rates; the current rates are one template applied to
  every country, so a US run carries a 20% standard rate.
- Category-aware product naming. Names follow
  `{brand} {root category} {token} {number}`, which is plausible but not
  merchandised - a laptop is not named like a specific laptop.
- Supplier-to-category affinity. Any supplier can currently supply any
  product; real catalogs cluster suppliers by category.
- Reference geography beyond six countries, and city names drawn from a real
  gazetteer rather than Faker.
- A `--format` option for the CSV, SQL, and Delta exporters that F000
  scaffolded but F001 does not populate.
