"""Generator for the warehouses master dataset.

A warehouse inherits its city, state, country, and coordinates from a real
city row, so its location is internally consistent. Capacities follow a
three-tier distribution - regional hubs are far larger than local spokes -
because a uniform capacity would be unrealistic for analytics demonstrations.
"""

from __future__ import annotations

from typing import Final

import polars as pl

from eds.config import MasterDataConfig
from eds.core.frames import build_frame, format_code
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.enums import WarehouseStatus
from eds.domains.retail.domain.supply_chain.schema import WAREHOUSES

__all__ = ["generate_warehouses"]

# (label, capacity range, relative weight) - hubs are rare, spokes common.
_CAPACITY_TIERS: Final[tuple[tuple[str, tuple[int, int], int], ...]] = (
    ("National Fulfillment Center", (800_000, 2_000_000), 1),
    ("Regional Distribution Center", (250_000, 800_000), 3),
    ("Local Delivery Station", (40_000, 250_000), 6),
)

_STATUSES: Final[tuple[WarehouseStatus, ...]] = (
    WarehouseStatus.ACTIVE,
    WarehouseStatus.MAINTENANCE,
    WarehouseStatus.INACTIVE,
    WarehouseStatus.CLOSED,
)
_STATUS_WEIGHTS: Final[tuple[int, ...]] = (90, 5, 3, 2)


def generate_warehouses(config: MasterDataConfig, cities: pl.DataFrame, seed: int) -> pl.DataFrame:
    """Generate the warehouses dataset.

    Args:
        config: Master data configuration supplying ``warehouse_count``.
        cities: The generated cities dataset, used to place each warehouse.
        seed: Run seed.

    Returns:
        ``config.warehouse_count`` rows keyed by sequential ``warehouse_id``.

    Raises:
        ValueError: If ``cities`` is empty, leaving nowhere to place warehouses.
    """
    if cities.is_empty():
        raise ValueError("cannot generate warehouses: the cities dataset is empty")

    rng = make_rng(seed, "warehouses")

    city_ids: list[int] = cities["city_id"].to_list()
    city_names: list[str] = cities["city_name"].to_list()
    state_ids: list[int] = cities["state_id"].to_list()
    country_ids: list[int] = cities["country_id"].to_list()
    latitudes: list[float] = cities["latitude"].to_list()
    longitudes: list[float] = cities["longitude"].to_list()

    tier_labels = [tier[0] for tier in _CAPACITY_TIERS]
    tier_weights = [tier[2] for tier in _CAPACITY_TIERS]
    tier_ranges = {tier[0]: tier[1] for tier in _CAPACITY_TIERS}

    warehouse_ids: list[int] = []
    codes: list[str] = []
    names: list[str] = []
    chosen_city_ids: list[int] = []
    chosen_state_ids: list[int] = []
    chosen_country_ids: list[int] = []
    capacities: list[int] = []
    statuses: list[str] = []
    warehouse_latitudes: list[float] = []
    warehouse_longitudes: list[float] = []

    for warehouse_id in range(1, config.warehouse_count + 1):
        index = rng.randrange(len(city_ids))
        label = rng.choices(tier_labels, weights=tier_weights, k=1)[0]
        capacity_low, capacity_high = tier_ranges[label]

        warehouse_ids.append(warehouse_id)
        codes.append(format_code("WH", warehouse_id, width=4))
        names.append(f"{city_names[index]} {label}")
        chosen_city_ids.append(city_ids[index])
        chosen_state_ids.append(state_ids[index])
        chosen_country_ids.append(country_ids[index])
        capacities.append(rng.randint(capacity_low, capacity_high))
        statuses.append(str(rng.choices(_STATUSES, weights=_STATUS_WEIGHTS, k=1)[0]))
        warehouse_latitudes.append(latitudes[index])
        warehouse_longitudes.append(longitudes[index])

    return build_frame(
        WAREHOUSES,
        {
            "warehouse_id": warehouse_ids,
            "warehouse_code": codes,
            "warehouse_name": names,
            "city_id": chosen_city_ids,
            "state_id": chosen_state_ids,
            "country_id": chosen_country_ids,
            "capacity_units": capacities,
            "status": statuses,
            "latitude": warehouse_latitudes,
            "longitude": warehouse_longitudes,
        },
    )
