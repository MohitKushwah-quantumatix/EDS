"""The ``eds generate`` command group.

Exposes master data generation to the command line. CLI options override the
values loaded from the configuration files, so a demo can be resized without
editing YAML.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

import polars as pl
import typer

from eds.adapters.parquet.reader import DatasetNotFoundError, read_datasets
from eds.adapters.parquet.writer import ExportError, write_datasets
from eds.config import (
    ConfigError,
    CustomerConfig,
    MasterDataConfig,
    PlatformConfig,
    SimulationConfig,
    load_config,
)
from eds.core.validation.issues import ValidationError
from eds.core.schema_export import SCHEMA_EXPORT_FILE, export_schema_json
from eds.runners.retail.dataset_registry import RETAIL_DATASET_SCHEMAS
from eds.domains.retail.generators.commerce.checkout_generator import (
    REQUIRED_CHECKOUT_DATASETS,
    generate_checkout_data,
)
from eds.domains.retail.generators.commerce.commerce import (
    REQUIRED_COMMERCE_DATASETS,
    generate_commerce_data,
)
from eds.domains.retail.generators.commerce.orders import (
    REQUIRED_ORDER_DATASETS,
    generate_order_data,
)
from eds.domains.retail.generators.commerce.payments import (
    REQUIRED_PAYMENT_DATASETS,
    generate_payment_data,
)
from eds.domains.retail.generators.commerce.returns import (
    REQUIRED_RETURN_DATASETS,
    generate_return_data,
)
from eds.domains.retail.generators.commerce.reviews import (
    REQUIRED_REVIEW_DATASETS,
    generate_review_data,
)
from eds.domains.retail.generators.commerce.shipments import (
    REQUIRED_SHIPMENT_DATASETS,
    generate_shipment_data,
)
from eds.domains.retail.generators.customer_data import (
    REQUIRED_MASTER_DATASETS,
    generate_customer_data,
)
from eds.domains.retail.generators.journey.browsing import (
    REQUIRED_BROWSING_DATASETS,
    generate_browsing_data,
)
from eds.domains.retail.generators.journey.engagement import (
    REQUIRED_ENGAGEMENT_DATASETS,
    generate_engagement_data,
)
from eds.domains.retail.generators.journey.journey import (
    REQUIRED_UPSTREAM_DATASETS,
    generate_journey_data,
)
from eds.domains.retail.generators.master_data import generate_master_data
from eds.domains.retail.validation.browsing_validation import validate_browsing_data
from eds.domains.retail.validation.checkout_validation import validate_checkout_data
from eds.domains.retail.validation.commerce_validation import validate_commerce_data
from eds.domains.retail.validation.customer_validation import validate_customer_data
from eds.domains.retail.validation.engagement_validation import validate_engagement_data
from eds.domains.retail.validation.journey_validation import validate_journey_data
from eds.domains.retail.validation.master_data import validate_master_data
from eds.domains.retail.validation.order_validation import validate_order_data
from eds.domains.retail.validation.payment_validation import validate_payment_data
from eds.domains.retail.validation.return_validation import validate_return_data
from eds.domains.retail.validation.review_validation import validate_review_data
from eds.domains.retail.validation.shipment_validation import validate_shipment_data

__all__ = ["generate_app", "master_data"]

generate_app = typer.Typer(
    name="generate",
    help="Generate simulator datasets.",
    no_args_is_help=True,
    add_completion=False,
)

_EXIT_CONFIG_ERROR = 2
_EXIT_VALIDATION_ERROR = 3
_EXIT_EXPORT_ERROR = 4


def _apply_overrides(
    config: SimulationConfig,
    seed: int | None = None,
    products: int | None = None,
    warehouses: int | None = None,
    suppliers: int | None = None,
    customers: int | None = None,
    output: Path | None = None,
) -> SimulationConfig:
    """Apply CLI overrides on top of the loaded configuration.

    Args:
        config: Configuration loaded from disk.
        seed: Override for the run seed.
        products: Override for the product count.
        warehouses: Override for the warehouse count.
        suppliers: Override for the supplier count.
        customers: Override for the customer count.
        output: Override for the output directory.

    Returns:
        A new configuration with the overrides applied.

    Raises:
        ConfigError: If the resulting configuration is invalid, for example a
            warehouse count below ``warehouses_per_product``.
    """
    platform_updates: dict[str, object] = {}
    if seed is not None:
        platform_updates["seed"] = seed
    if output is not None:
        platform_updates["output_directory"] = output

    master_updates: dict[str, object] = {}
    if products is not None:
        master_updates["product_count"] = products
    if warehouses is not None:
        master_updates["warehouse_count"] = warehouses
    if suppliers is not None:
        master_updates["supplier_count"] = suppliers

    customer_updates: dict[str, object] = {}
    if customers is not None:
        customer_updates["customer_count"] = customers

    try:
        platform = (
            PlatformConfig.model_validate({**config.platform.model_dump(), **platform_updates})
            if platform_updates
            else config.platform
        )
        master = (
            MasterDataConfig.model_validate({**config.master_data.model_dump(), **master_updates})
            if master_updates
            else config.master_data
        )
        customer = (
            CustomerConfig.model_validate({**config.customers.model_dump(), **customer_updates})
            if customer_updates
            else config.customers
        )
    except ValueError as exc:
        raise ConfigError(f"Invalid command-line override: {exc}") from exc

    # Sections without command-line overrides are carried through unchanged;
    # omitting them here would silently reset them to their defaults.
    return SimulationConfig(
        platform=platform,
        master_data=master,
        customers=customer,
        journey=config.journey,
        browsing=config.browsing,
        engagement=config.engagement,
        commerce=config.commerce,
        checkout=config.checkout,
        orders=config.orders,
        payments=config.payments,
        shipments=config.shipments,
        returns=config.returns,
        reviews=config.reviews,
    )


def _report(datasets: Mapping[str, pl.DataFrame], seed: int, destination: Path) -> None:
    """Print a per-dataset row count summary.

    Args:
        datasets: The generated datasets, keyed by name.
        seed: The seed the run used.
        destination: Directory the datasets were written to.
    """
    counts = {name: frame.height for name, frame in datasets.items()}
    typer.echo(f"Seed: {seed}")
    typer.echo(f"Output: {destination}")
    width = max(len(name) for name in counts)
    for name, count in counts.items():
        typer.echo(f"  {name:<{width}}  {count:>12,} rows")
    typer.echo(f"Total: {sum(counts.values()):,} rows across {len(counts)} datasets")


def _export_schema(datasets: Mapping[str, pl.DataFrame], output_directory: Path) -> None:
    """Update schema.json with declarations for whatever was just written.

    Merges into any schema.json already present (from an earlier stage's
    run), so the four `eds generate` commands build up one complete file
    between them regardless of the order they're run in.
    """
    known = {name: RETAIL_DATASET_SCHEMAS[name] for name in datasets if name in RETAIL_DATASET_SCHEMAS}
    export_schema_json(known, output_directory / SCHEMA_EXPORT_FILE)


@generate_app.command("master-data")
def master_data(
    seed: Annotated[
        int | None, typer.Option("--seed", help="Random seed. Overrides simulation.yaml.")
    ] = None,
    products: Annotated[
        int | None, typer.Option("--products", min=1, help="Number of products to generate.")
    ] = None,
    warehouses: Annotated[
        int | None, typer.Option("--warehouses", min=1, help="Number of warehouses.")
    ] = None,
    suppliers: Annotated[
        int | None, typer.Option("--suppliers", min=1, help="Number of suppliers.")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Output directory for Parquet files.")
    ] = None,
    config_dir: Annotated[
        Path | None, typer.Option("--config-dir", help="Directory holding the YAML config files.")
    ] = None,
    validate: Annotated[
        bool, typer.Option("--validate/--no-validate", help="Validate before writing.")
    ] = True,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Generate and validate without writing files.")
    ] = False,
) -> None:
    """Generate the master datasets and write them as Parquet.

    Exits with code 2 on configuration errors, 3 on validation failures, and
    4 when the datasets cannot be written.
    """
    try:
        config = load_config(config_dir)
        config = _apply_overrides(
            config,
            seed=seed,
            products=products,
            warehouses=warehouses,
            suppliers=suppliers,
            output=output,
        )
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    try:
        data = generate_master_data(config)
    except (KeyError, ValueError) as exc:
        typer.echo(f"Generation failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    if validate:
        issues = validate_master_data(data.datasets)
        if issues:
            error = ValidationError(issues)
            typer.echo(f"Validation failed: {error}", err=True)
            raise typer.Exit(code=_EXIT_VALIDATION_ERROR)
        typer.echo("Validation passed.")

    if dry_run:
        typer.echo("Dry run: no files written.")
        _report(data.datasets, data.seed, config.platform.output_directory)
        return

    try:
        write_datasets(data.datasets, config.platform.output_directory)
        _export_schema(data.datasets, config.platform.output_directory)
    except ExportError as exc:
        typer.echo(f"Export failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_EXPORT_ERROR) from exc

    _report(data.datasets, data.seed, config.platform.output_directory)


@generate_app.command("customers")
def customers(
    seed: Annotated[
        int | None, typer.Option("--seed", help="Random seed. Overrides simulation.yaml.")
    ] = None,
    customers_count: Annotated[
        int | None,
        typer.Option("--customers", min=1, help="Number of customers to generate."),
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Output directory for Parquet files.")
    ] = None,
    master_data_dir: Annotated[
        Path | None,
        typer.Option(
            "--master-data",
            help="Directory holding the F001 Parquet files. Defaults to the output directory.",
        ),
    ] = None,
    config_dir: Annotated[
        Path | None, typer.Option("--config-dir", help="Directory holding the YAML config files.")
    ] = None,
    validate: Annotated[
        bool, typer.Option("--validate/--no-validate", help="Validate before writing.")
    ] = True,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Generate and validate without writing files.")
    ] = False,
) -> None:
    """Generate the customer datasets and write them as Parquet.

    Reads the F001 geography datasets rather than regenerating them, so
    `eds generate master-data` must have been run first.

    Exits with code 2 on configuration errors, 3 on validation failures, and
    4 when the datasets cannot be written.
    """
    try:
        config = load_config(config_dir)
        config = _apply_overrides(config, seed=seed, customers=customers_count, output=output)
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    source = master_data_dir or config.platform.output_directory
    try:
        master = read_datasets(REQUIRED_MASTER_DATASETS, source)
    except DatasetNotFoundError as exc:
        typer.echo(f"Master data not found: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    try:
        data = generate_customer_data(config, master)
    except (KeyError, ValueError) as exc:
        typer.echo(f"Generation failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    if validate:
        issues = validate_customer_data(
            {**master, **data.datasets},
            config.customers.min_addresses,
            config.customers.max_addresses,
        )
        if issues:
            error = ValidationError(issues)
            typer.echo(f"Validation failed: {error}", err=True)
            raise typer.Exit(code=_EXIT_VALIDATION_ERROR)
        typer.echo("Validation passed.")

    if dry_run:
        typer.echo("Dry run: no files written.")
        _report(data.datasets, data.seed, config.platform.output_directory)
        return

    try:
        write_datasets(data.datasets, config.platform.output_directory)
        _export_schema(data.datasets, config.platform.output_directory)
    except ExportError as exc:
        typer.echo(f"Export failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_EXPORT_ERROR) from exc

    _report(data.datasets, data.seed, config.platform.output_directory)


@generate_app.command("journey")
def journey(
    seed: Annotated[
        int | None, typer.Option("--seed", help="Random seed. Overrides simulation.yaml.")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Output directory for Parquet files.")
    ] = None,
    source_dir: Annotated[
        Path | None,
        typer.Option(
            "--source",
            help="Directory holding the F001 and F002 Parquet files. "
            "Defaults to the output directory.",
        ),
    ] = None,
    config_dir: Annotated[
        Path | None, typer.Option("--config-dir", help="Directory holding the YAML config files.")
    ] = None,
    validate: Annotated[
        bool, typer.Option("--validate/--no-validate", help="Validate before writing.")
    ] = True,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Generate and validate without writing files.")
    ] = False,
) -> None:
    """Generate the customer journey datasets as Parquet.

    Produces personas, sessions, category views, searches, product views, and
    wishlists.

    Reads the F001 master data and F002 customer datasets rather than
    regenerating them, so both must have been generated first.

    Exits with code 2 on configuration errors, 3 on validation failures, and
    4 when the datasets cannot be written.
    """
    try:
        config = load_config(config_dir)
        config = _apply_overrides(config, seed=seed, output=output)
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    # The command produces both features' datasets, so it reads what F003.1
    # needs plus what F003.2 needs, minus the datasets F003.1 itself produces.
    produced_here = {
        "customer_personas",
        "sessions",
        "category_views",
        "search_history",
    }
    needed = dict.fromkeys(
        (
            *REQUIRED_UPSTREAM_DATASETS,
            *(name for name in REQUIRED_BROWSING_DATASETS if name not in produced_here),
            *(name for name in REQUIRED_ENGAGEMENT_DATASETS if name not in produced_here),
        )
    )

    source = source_dir or config.platform.output_directory
    try:
        upstream = read_datasets(needed, source)
    except DatasetNotFoundError as exc:
        typer.echo(f"Upstream data not found: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    try:
        data = generate_journey_data(config, upstream)
        browsing = generate_browsing_data(config, {**upstream, **data.datasets})
        engagement = generate_engagement_data(
            config, {**upstream, **data.datasets, **browsing.datasets}
        )
    except (KeyError, ValueError) as exc:
        typer.echo(f"Generation failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    produced = {**data.datasets, **browsing.datasets, **engagement.datasets}

    if validate:
        issues = validate_journey_data(
            {**upstream, **produced},
            config.customers.reference_date,
            config.journey.session_years,
            config.journey.max_pages_viewed,
        )
        issues += validate_browsing_data(
            {**upstream, **produced},
            config.browsing.min_view_seconds,
            config.browsing.max_view_seconds,
            config.browsing.max_results_count,
        )
        issues += validate_engagement_data(
            {**upstream, **produced},
            config.engagement.min_view_seconds,
            config.engagement.max_view_seconds,
        )
        if issues:
            error = ValidationError(issues)
            typer.echo(f"Validation failed: {error}", err=True)
            raise typer.Exit(code=_EXIT_VALIDATION_ERROR)
        typer.echo("Validation passed.")

    if dry_run:
        typer.echo("Dry run: no files written.")
        _report(produced, data.seed, config.platform.output_directory)
        return

    try:
        write_datasets(produced, config.platform.output_directory)
        _export_schema(produced, config.platform.output_directory)
    except ExportError as exc:
        typer.echo(f"Export failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_EXPORT_ERROR) from exc

    _report(produced, data.seed, config.platform.output_directory)


@generate_app.command("commerce")
def commerce(
    seed: Annotated[
        int | None, typer.Option("--seed", help="Random seed. Overrides simulation.yaml.")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", help="Output directory for Parquet files.")
    ] = None,
    source_dir: Annotated[
        Path | None,
        typer.Option(
            "--source",
            help="Directory holding the earlier Parquet files. Defaults to the output directory.",
        ),
    ] = None,
    config_dir: Annotated[
        Path | None, typer.Option("--config-dir", help="Directory holding the YAML config files.")
    ] = None,
    validate: Annotated[
        bool, typer.Option("--validate/--no-validate", help="Validate before writing.")
    ] = True,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Generate and validate without writing files.")
    ] = False,
) -> None:
    """Generate the commerce datasets as Parquet.

    Produces shopping carts, cart items, checkouts, orders, order lines, order
    status history, payments, payment status history, shipments, shipment
    items, shipment status history, returns, return items, return status
    history, and reviews.

    Reads the master data, customer, and journey datasets rather than
    regenerating them, so those commands must have been run first.

    Exits with code 2 on configuration errors, 3 on validation failures, and
    4 when the datasets cannot be written.
    """
    try:
        config = load_config(config_dir)
        config = _apply_overrides(config, seed=seed, output=output)
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    # The command produces every commerce feature's datasets, so it reads the
    # union of what they need, minus the datasets it produces itself.
    produced_here = {
        "shopping_carts",
        "cart_items",
        "checkout",
        "orders",
        "order_lines",
        "order_status_history",
        "payments",
        "payment_status_history",
        "shipments",
        "shipment_items",
        "shipment_status_history",
        "returns",
        "return_items",
        "return_status_history",
    }
    needed = dict.fromkeys(
        (
            *REQUIRED_COMMERCE_DATASETS,
            *(name for name in REQUIRED_CHECKOUT_DATASETS if name not in produced_here),
            *(name for name in REQUIRED_ORDER_DATASETS if name not in produced_here),
            *(name for name in REQUIRED_PAYMENT_DATASETS if name not in produced_here),
            *(name for name in REQUIRED_SHIPMENT_DATASETS if name not in produced_here),
            *(name for name in REQUIRED_RETURN_DATASETS if name not in produced_here),
            *(name for name in REQUIRED_REVIEW_DATASETS if name not in produced_here),
        )
    )

    source = source_dir or config.platform.output_directory
    try:
        upstream = read_datasets(needed, source)
    except DatasetNotFoundError as exc:
        typer.echo(f"Upstream data not found: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    try:
        data = generate_commerce_data(config, upstream)
        checkout = generate_checkout_data(config, {**upstream, **data.datasets})
        orders = generate_order_data(config, {**upstream, **data.datasets, **checkout.datasets})
        earlier = {**upstream, **data.datasets, **checkout.datasets, **orders.datasets}
        payments = generate_payment_data(config, earlier)
        shipments = generate_shipment_data(config, {**earlier, **payments.datasets})
        fulfilled = {**earlier, **payments.datasets, **shipments.datasets}
        returns = generate_return_data(config, fulfilled)
        reviews = generate_review_data(config, {**fulfilled, **returns.datasets})
    except (KeyError, ValueError) as exc:
        typer.echo(f"Generation failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_CONFIG_ERROR) from exc

    produced = {
        **data.datasets,
        **checkout.datasets,
        **orders.datasets,
        **payments.datasets,
        **shipments.datasets,
        **returns.datasets,
        **reviews.datasets,
    }

    if validate:
        issues = validate_commerce_data(
            {**upstream, **produced},
            config.commerce.min_quantity,
            config.commerce.max_quantity,
        )
        issues += validate_checkout_data({**upstream, **produced})
        issues += validate_order_data({**upstream, **produced})
        issues += validate_payment_data({**upstream, **produced})
        issues += validate_shipment_data({**upstream, **produced}, config.shipments.carriers)
        issues += validate_return_data({**upstream, **produced}, config.returns.refund_types)
        issues += validate_review_data(
            {**upstream, **produced}, config.reviews.titles, config.reviews.texts
        )
        if issues:
            error = ValidationError(issues)
            typer.echo(f"Validation failed: {error}", err=True)
            raise typer.Exit(code=_EXIT_VALIDATION_ERROR)
        typer.echo("Validation passed.")

    if dry_run:
        typer.echo("Dry run: no files written.")
        _report(produced, data.seed, config.platform.output_directory)
        return

    try:
        write_datasets(produced, config.platform.output_directory)
        _export_schema(produced, config.platform.output_directory)
    except ExportError as exc:
        typer.echo(f"Export failed: {exc}", err=True)
        raise typer.Exit(code=_EXIT_EXPORT_ERROR) from exc

    _report(produced, data.seed, config.platform.output_directory)
