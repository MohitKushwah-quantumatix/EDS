# Enterprise Data Simulator (EDS)

EDS generates synthetic enterprise datasets by **simulating business events**
rather than by sampling rows in isolation.

The model is deliberately simple:

1. Business events drive state changes.
2. State changes produce data.
3. Referential integrity is maintained across every produced record.
4. Chronological consistency is preserved across the simulated timeline.
5. Runs are deterministic when a random seed is provided.

> **Status: version 1.0 complete.** Every feature from F000 to F010 has
> shipped: the repository foundation, master data, customers, the digital
> journey (personas and sessions, category browsing and search, product views
> and wishlists), and commerce end to end — shopping carts, checkout, orders,
> payments, shipments, returns, and product reviews. Four commands produce
> thirty-nine referentially consistent datasets.

## Requirements

- Python 3.12 or newer

## Installation

Install in editable mode with the development tooling:

```bash
python -m pip install -e ".[dev]"
```

## Usage

```bash
eds --help
eds version
```

Generate the datasets as Parquet:

```bash
eds generate master-data                         # uses configs/
eds generate master-data --seed 42 --products 50000
eds generate master-data --dry-run               # generate and validate only

eds generate customers                           # requires master data first
eds generate customers --customers 1000 --seed 42

eds generate journey                             # requires customers first
eds generate journey --seed 42

eds generate commerce                            # requires journey first
eds generate commerce --seed 42
```

`generate journey` produces six datasets: personas and sessions (F003.1),
category views and searches (F003.2), and product views and wishlists
(F003.3). `generate commerce` then adds shopping carts and cart items (F004),
checkouts (F005), orders with their lines and status history (F006), payments
with their status history (F007), shipments with their items and status
history (F008), returns with their items and status history (F009), and
product reviews (F010).

Each command reads what the previous one wrote rather than regenerating it, so
run them in order. Point a command at a different source directory with
`--master-data <dir>` or `--source <dir>`.

The run prints the seed it used, so a non-deterministic run can be replayed
exactly. Exit codes are `2` for configuration errors, `3` for validation
failures, and `4` for export failures.

The package version is public API:

```python
from eds.version import __version__
```

## Configuration

[`configs/simulation.yaml`](configs/simulation.yaml) holds platform settings -
seed, timezone, locale, output directory.
[`configs/logging.yaml`](configs/logging.yaml) holds logging defaults.
[`configs/master_data.yaml`](configs/master_data.yaml) holds business settings
for F001: entity volumes, category tree shape, and geographic coverage.
[`configs/customers.yaml`](configs/customers.yaml) holds F002 settings:
customer count, addresses per customer, and the registration window.
[`configs/journey.yaml`](configs/journey.yaml) holds F003.1 settings: bounce
rate, page ceiling, and the session window.
[`configs/browsing.yaml`](configs/browsing.yaml) holds F003.2 settings:
category views and searches per session, view durations, and result counts.
[`configs/engagement.yaml`](configs/engagement.yaml) holds F003.3 settings:
product views per category view, dwell times, and the wishlist rate.
[`configs/commerce.yaml`](configs/commerce.yaml) holds F004 settings: the cart
rate, quantities, cart size ceiling, and removal rate.
[`configs/checkout.yaml`](configs/checkout.yaml) holds F005 settings: tax band,
address reuse, and checkout duration.
[`configs/orders.yaml`](configs/orders.yaml) holds F006 settings: the lifecycle
rates, transition waits, and order number prefix.
[`configs/payments.yaml`](configs/payments.yaml) holds F007 settings: currency,
the capture, void and failure rates, transition waits, and the payment
reference prefix.
[`configs/shipments.yaml`](configs/shipments.yaml) holds F008 settings: the
carriers and delivery windows per shipping method, the completion rates,
transition waits, and the shipment and tracking number prefixes.
[`configs/returns.yaml`](configs/returns.yaml) holds F009 settings: the return
rate, refund types, lifecycle rates, transition waits, and the return number
prefix. Return *reasons* are master data, not configuration.
[`configs/reviews.yaml`](configs/reviews.yaml) holds F010 settings: the review
rate, star rating weights, the titles and one-sentence bodies offered for each
rating, the writing delay, and the review number prefix.
[`configs/evolution.yaml`](configs/evolution.yaml) holds the four rates that
describe *change* rather than shape: customers registering per simulated day,
the share of the base that returns, sessions per returning customer, and loyalty
points per unit of spend. Only the second and later simulated days use them, and
it is the one configuration file that may be absent.

## Datasets

F001 generates fourteen referentially consistent master datasets:

| Group | Datasets |
| --- | --- |
| Geography | `countries`, `states`, `cities` |
| Product catalog | `categories`, `brands`, `products` |
| Supply chain | `suppliers`, `warehouses`, `inventory` |
| Commercial | `payment_methods`, `shipping_methods`, `tax_codes`, `coupon_types`, `return_reasons` |

The later features add twenty-five more on top of them, for thirty-nine in
total:

| Group | Datasets |
| --- | --- |
| Customers | `customers`, `customer_addresses`, `customer_preferences`, `customer_loyalty` |
| Journey | `customer_personas`, `sessions`, `category_views`, `search_history`, `product_views`, `wishlists` |
| Commerce | `shopping_carts`, `cart_items`, `checkout` |
| Orders | `orders`, `order_lines`, `order_status_history` |
| Payments | `payments`, `payment_status_history` |
| Shipments | `shipments`, `shipment_items`, `shipment_status_history` |
| Returns | `returns`, `return_items`, `return_status_history` |
| Reviews | `reviews` |

Countries and their subdivisions are real; cities, the catalog, customers, and
their sessions are synthesised on top. Customer addresses and sessions
reference the F001 geography, never invented locations. The same seed always
produces the same output.

The commerce datasets form one chain, each link narrowing the one before it: a
session may open a cart, a cart may reach checkout, a successful checkout
becomes an order, a paid order ships, a delivered shipment may come back, and a
delivered item that was kept may be reviewed. At the default 1,000-customer
scale that runs from 5,752 sessions down to 58 reviews.

## Development

| Task        | Command             |
| ----------- | ------------------- |
| Run tests   | `pytest`            |
| Long runs   | `pytest -m slow`    |
| Lint        | `ruff check .`      |
| Format      | `ruff format .`     |
| Type check  | `mypy eds`          |

`pytest` excludes tests marked `slow` — simulations long enough to be measured
in minutes, kept because their length is the claim but excluded because they
assert nothing a shorter run does not.

## Architecture

EDS is a **platform** with Retail as its first domain. Four layers, with a
dependency direction enforced by tests:

| Layer | Package | Owns |
| --- | --- | --- |
| Core | [`eds/core/`](eds/core/) | Dataset schema, deterministic random streams, frame helpers, the validation framework, config loading |
| Platform | [`eds/platform/`](eds/platform/) | Project identity, metadata, the domain registry |
| Domains | [`eds/domains/retail/`](eds/domains/retail/) | Retail entities, generators, business rules, settings |
| Adapters | [`eds/adapters/`](eds/adapters/) | Where output goes. Parquet today |

`core` depends on nothing else; `domains` and `adapters` never import each
other; only the CLI composes them.

## Documentation

**[`docs/`](docs/README.md) is the official documentation suite** — five
documents covering EDS from zero knowledge to safe contribution:

| Document | Audience |
| --- | --- |
| [Handbook](docs/01_Handbook.md) | Everyone. Concepts, installation, configuration, running, output, troubleshooting |
| [Architecture Reference](docs/02_Architecture_Reference.md) | Architects. The design and all seventeen platform decision records |
| [Maintainer Guide](docs/03_Maintainer_Guide.md) | Maintainers. How to evolve EDS safely |
| [Package Reference](docs/04_Package_Reference.md) | Developers. Every package, class and extension point |
| [Developer Quick Start](docs/05_Developer_Quick_Start.md) | New developers. Productive in under 30 minutes |

[`docs/platform/`](docs/platform/) holds the platform vision, the layer
architecture, the roadmap, and PADR-001 to PADR-017 — the decisions that govern
where code may live and what may depend on what.

[`docs/architecture/`](docs/architecture/) holds the feature decision records.
ADR-006 to ADR-011 govern every feature from F006 onward: completed features
are frozen, financial values come from the checkout, each entity has exactly
one parent, transactional data is derived rather than sampled, state changes go
in history tables, and collections live in their own datasets. These are
Retail's rules and moved with Retail; they remain in force unchanged.
ADR-013 and ADR-014 add what a *passing day* does: a day is added to a history
rather than replacing it, and every dataset declares whether it is static,
append-only, a mutable snapshot or slowly changing.

Pre-platform import paths such as `eds.config` and `eds.generators.commerce`
still work and resolve to the same objects, so existing code needs no change.

## Repository layout

```
enterprise-data-simulator/
├── docs/
│   ├── platform/         Platform vision, architecture, roadmap, PADR-001..005
│   ├── architecture/     Feature decision records, ADR-001..014
│   └── features/         One folder per feature: context, prompt, review
├── configs/              Configuration (YAML), one file per feature
├── eds/
│   ├── core/             Shared infrastructure. No business, no storage
│   │   ├── schema.py         Dataset and ForeignKey declarations
│   │   ├── frames.py         Schema-conformant frame construction
│   │   ├── random_streams.py Deterministic named random streams
│   │   ├── config.py         PlatformConfig and YAML loading
│   │   └── validation/       Schema, key and foreign-key framework
│   ├── platform/         Simulation lifecycle
│   │   ├── project/          Durable identity and state
│   │   ├── execution/        Planning - what should run, in what order
│   │   ├── time/             What time means - period, tick, calendar, clock
│   │   ├── run/              Project + plan + clock, bound and validated
│   │   ├── runtime/          Results, events, failures - facts, no behaviour
│   │   ├── scheduler/        Runs a simulation. The first executable component
│   ├── runners/
│   │   └── retail/        Retail wired into the platform. Imports both sides
│   │   ├── metadata.py       Platform name and contract version
│   │   ├── domain.py         SimulationDomain protocol and registry
│   │   └── state.py          Placeholder - not implemented
│   ├── domains/
│   │   └── retail/       The Retail domain
│   │       ├── config.py     Retail settings models and loaders
│   │       ├── domain/       Entity schemas and enums
│   │       ├── generators/   Business event generators
│   │       ├── temporal/     What one simulated day does to the business
│   │       └── validation/   Retail business rules
│   ├── adapters/
│   │   ├── base.py           DatasetWriter and DatasetReader protocols
│   │   └── parquet/          Reader, writer, ParquetAdapter
│   ├── cli/              Typer command-line interface
│   ├── tests/            Test suite
│   └── domain/ generators/ validation/ exporters/ config.py
│                         Pre-platform import paths, kept working (PADR-005)
├── pyproject.toml
├── pytest.ini
├── ruff.toml
└── README.md
```

## Technology

Polars, Pydantic, Faker, Typer, and PyYAML, with PyTest, Ruff, and mypy for
development.

## License

Released under the [MIT License](LICENSE).
