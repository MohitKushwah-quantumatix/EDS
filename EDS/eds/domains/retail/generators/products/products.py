"""Generator for the products master dataset.

Products are the largest catalog dataset, so generation is batched:
:func:`iter_product_batches` yields fixed-size frames that a caller can write
incrementally, while :func:`generate_products` concatenates them for callers
that want the whole catalog in memory.

Every product attaches to a leaf category, and its price band is chosen from
that category's level-1 ancestor, so a laptop is never priced like a banana.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from typing import Final

import polars as pl

from eds.config import MasterDataConfig
from eds.core.frames import build_frame, empty_frame, format_code
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.catalog.schema import PRODUCTS
from eds.domains.retail.domain.enums import ProductStatus, UnitOfMeasure
from eds.domains.retail.generators.pricing.generator import generate_price_point, price_band_for
from eds.domains.retail.generators.products.categories import leaf_category_roots

__all__ = ["ProductInputs", "generate_products", "iter_product_batches"]

_SERIES_TOKENS: Final[tuple[str, ...]] = (
    "Pro",
    "Max",
    "Lite",
    "Plus",
    "Ultra",
    "Classic",
    "Series",
    "Edition",
)

_STATUSES: Final[tuple[ProductStatus, ...]] = (
    ProductStatus.ACTIVE,
    ProductStatus.PENDING_LAUNCH,
    ProductStatus.INACTIVE,
    ProductStatus.DISCONTINUED,
)
_STATUS_WEIGHTS: Final[tuple[int, ...]] = (88, 4, 4, 4)

_GROCERY_UNITS: Final[tuple[UnitOfMeasure, ...]] = (
    UnitOfMeasure.EACH,
    UnitOfMeasure.PACK,
    UnitOfMeasure.KILOGRAM,
    UnitOfMeasure.GRAM,
    UnitOfMeasure.LITRE,
    UnitOfMeasure.MILLILITRE,
)
_GENERAL_UNITS: Final[tuple[UnitOfMeasure, ...]] = (
    UnitOfMeasure.EACH,
    UnitOfMeasure.PACK,
    UnitOfMeasure.CASE,
)
_GENERAL_UNIT_WEIGHTS: Final[tuple[int, ...]] = (85, 12, 3)

_NON_RETURNABLE_ROOTS: Final[frozenset[str]] = frozenset({"Grocery", "Health & Beauty"})
_RETURNABLE_PROBABILITY: Final[float] = 0.94
_NON_RETURNABLE_ROOT_PROBABILITY: Final[float] = 0.35


class ProductInputs:
    """Pre-extracted lookup columns needed to generate products.

    Building these lists once avoids re-reading Polars columns per batch,
    which dominates runtime at large product counts.

    Attributes:
        leaf_category_ids: Category ids products may attach to.
        leaf_root_names: Level-1 ancestor name for each leaf category.
        brand_ids: Available brand ids.
        brand_names: Brand name for each brand id, same order.
        supplier_ids: Available supplier ids.
        tax_code_ids: Available tax code ids.
    """

    def __init__(
        self,
        categories: pl.DataFrame,
        brands: pl.DataFrame,
        suppliers: pl.DataFrame,
        tax_codes: pl.DataFrame,
    ) -> None:
        """Extract lookup columns from the upstream datasets.

        Args:
            categories: The generated categories dataset.
            brands: The generated brands dataset.
            suppliers: The generated suppliers dataset.
            tax_codes: The generated tax codes dataset.

        Raises:
            ValueError: If any upstream dataset is empty, which would leave a
                product foreign key with nothing to point at.
        """
        roots = leaf_category_roots(categories)
        if not roots:
            raise ValueError("cannot generate products: no leaf categories exist")
        if brands.is_empty():
            raise ValueError("cannot generate products: the brands dataset is empty")
        if suppliers.is_empty():
            raise ValueError("cannot generate products: the suppliers dataset is empty")
        if tax_codes.is_empty():
            raise ValueError("cannot generate products: the tax codes dataset is empty")

        self.leaf_category_ids: list[int] = list(roots)
        self.leaf_root_names: list[str] = [roots[key] for key in self.leaf_category_ids]
        self.brand_ids: list[int] = brands["brand_id"].to_list()
        self.brand_names: list[str] = brands["brand_name"].to_list()
        self.supplier_ids: list[int] = suppliers["supplier_id"].to_list()
        self.tax_code_ids: list[int] = tax_codes["tax_code_id"].to_list()


def _unit_of_measure(rng: random.Random, root_name: str) -> UnitOfMeasure:
    """Choose a plausible selling unit for a product.

    Args:
        rng: Random source.
        root_name: Level-1 category name.

    Returns:
        A unit of measure appropriate to the category.
    """
    if root_name == "Grocery":
        return rng.choice(_GROCERY_UNITS)
    return rng.choices(_GENERAL_UNITS, weights=_GENERAL_UNIT_WEIGHTS, k=1)[0]


def _dimensions(rng: random.Random, weight_kg: float) -> tuple[float, float, float]:
    """Derive plausible package dimensions from a weight.

    Args:
        rng: Random source.
        weight_kg: Product weight in kilograms.

    Returns:
        Length, width, and height in centimetres.
    """
    base = 8.0 + (weight_kg**0.4) * 12.0
    length = round(base * rng.uniform(0.8, 1.6), 1)
    width = round(base * rng.uniform(0.6, 1.1), 1)
    height = round(base * rng.uniform(0.3, 0.9), 1)
    return length, width, height


def _sample_weight(rng: random.Random) -> float:
    """Sample a right-skewed product weight in kilograms.

    Most retail items are light, with a thin tail of heavy goods such as
    furniture and appliances.

    Args:
        rng: Random source.

    Returns:
        A weight between 0.01 kg and roughly 60 kg.
    """
    return min(60.0, max(0.01, rng.lognormvariate(mu=-0.4, sigma=1.1)))


def iter_product_batches(
    config: MasterDataConfig,
    inputs: ProductInputs,
    seed: int,
    reference_date: date,
    currency_code: str = "USD",
) -> Iterator[pl.DataFrame]:
    """Yield products in batches of ``config.batch_size``.

    Args:
        config: Master data configuration supplying counts and batch size.
        inputs: Pre-extracted foreign key pools.
        seed: Run seed.
        currency_code: ISO 4217 code recorded on every product.

    Yields:
        Frames matching the products schema. The final batch may be smaller.
    """
    rng = make_rng(seed, "products")
    remaining = config.product_count
    next_product_id = 1

    while remaining > 0:
        size = min(config.batch_size, remaining)

        product_ids: list[int] = []
        skus: list[str] = []
        names: list[str] = []
        category_ids: list[int] = []
        brand_ids: list[int] = []
        supplier_ids: list[int] = []
        tax_code_ids: list[int] = []
        units: list[str] = []
        unit_costs: list[float] = []
        list_prices: list[float] = []
        currencies: list[str] = []
        weights: list[float] = []
        lengths: list[float] = []
        widths: list[float] = []
        heights: list[float] = []
        statuses: list[str] = []
        returnable_flags: list[bool] = []
        effective_dates: list[date] = []
        end_dates: list[date | None] = []

        for _ in range(size):
            leaf_index = rng.randrange(len(inputs.leaf_category_ids))
            category_id = inputs.leaf_category_ids[leaf_index]
            root_name = inputs.leaf_root_names[leaf_index]
            brand_index = rng.randrange(len(inputs.brand_ids))
            price_point = generate_price_point(rng, price_band_for(root_name))
            weight = round(_sample_weight(rng), 3)
            length, width, height = _dimensions(rng, weight)
            returnable_odds = (
                _NON_RETURNABLE_ROOT_PROBABILITY
                if root_name in _NON_RETURNABLE_ROOTS
                else _RETURNABLE_PROBABILITY
            )

            product_ids.append(next_product_id)
            skus.append(format_code("SKU", next_product_id, width=8))
            names.append(
                f"{inputs.brand_names[brand_index]} {root_name.split(' &')[0]} "
                f"{rng.choice(_SERIES_TOKENS)} {rng.randint(100, 9999)}"
            )
            category_ids.append(category_id)
            brand_ids.append(inputs.brand_ids[brand_index])
            supplier_ids.append(rng.choice(inputs.supplier_ids))
            tax_code_ids.append(rng.choice(inputs.tax_code_ids))
            units.append(str(_unit_of_measure(rng, root_name)))
            unit_costs.append(price_point.unit_cost)
            list_prices.append(price_point.list_price)
            currencies.append(currency_code)
            weights.append(weight)
            lengths.append(length)
            widths.append(width)
            heights.append(height)
            statuses.append(str(rng.choices(_STATUSES, weights=_STATUS_WEIGHTS, k=1)[0]))
            returnable_flags.append(rng.random() < returnable_odds)
            effective_dates.append(reference_date)
            end_dates.append(None)

            next_product_id += 1

        yield build_frame(
            PRODUCTS,
            {
                "product_id": product_ids,
                "sku": skus,
                "product_name": names,
                "category_id": category_ids,
                "brand_id": brand_ids,
                "supplier_id": supplier_ids,
                "tax_code_id": tax_code_ids,
                "unit_of_measure": units,
                "unit_cost": unit_costs,
                "list_price": list_prices,
                "currency_code": currencies,
                "weight_kg": weights,
                "length_cm": lengths,
                "width_cm": widths,
                "height_cm": heights,
                "status": statuses,
                "is_returnable": returnable_flags,
                "effective_date": effective_dates,
                "end_date": end_dates,
            },
        )
        remaining -= size


def generate_products(
    config: MasterDataConfig,
    categories: pl.DataFrame,
    brands: pl.DataFrame,
    suppliers: pl.DataFrame,
    tax_codes: pl.DataFrame,
    seed: int,
    reference_date: date,
    currency_code: str = "USD",
) -> pl.DataFrame:
    """Generate the complete products dataset.

    Args:
        config: Master data configuration.
        categories: The generated categories dataset.
        brands: The generated brands dataset.
        suppliers: The generated suppliers dataset.
        tax_codes: The generated tax codes dataset.
        seed: Run seed.
        currency_code: ISO 4217 code recorded on every product.

    Returns:
        ``config.product_count`` rows keyed by sequential ``product_id``.

    Raises:
        ValueError: If any upstream dataset is empty.
    """
    inputs = ProductInputs(categories, brands, suppliers, tax_codes)
    batches = list(iter_product_batches(config, inputs, seed, reference_date, currency_code))
    return pl.concat(batches, how="vertical") if batches else empty_frame(PRODUCTS)
