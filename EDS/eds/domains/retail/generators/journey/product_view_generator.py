"""Generator for the product views dataset.

A product view is a click from a category page into a product. Three rules
shape the data:

* **The product comes from the category being browsed.** F001 attaches
  products to leaf categories only, while F003.2 browses categories at every
  level, so a view of ``Electronics`` draws from every product in the
  ``Electronics`` subtree. A leaf category view still draws only that leaf's
  products.
* **Products are not chosen uniformly.** A weighted popularity model gives the
  top fifth of the catalog roughly seventy per cent of all views.
* **A search-sourced view points at a real search.** ``view_source`` is drawn
  from a distribution conditioned on whether the category view actually
  produced a search, so the overall marginal still matches the specified
  split without ever inventing a search that does not exist.
"""

from __future__ import annotations

import bisect
import math
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

import polars as pl

from eds.config import EngagementConfig
from eds.core.frames import build_frame, empty_frame
from eds.core.random_streams import make_rng, stream_seed
from eds.domains.retail.domain.journey.enums import PersonaName, ViewSource
from eds.domains.retail.domain.journey.schema import PRODUCT_VIEWS

__all__ = [
    "PERSONA_ENGAGEMENT_PROFILES",
    "POPULARITY_TIERS",
    "PersonaEngagementProfile",
    "ProductCatalog",
    "generate_product_views",
    "iter_product_view_batches",
    "persona_engagement_profile",
]


@dataclass(frozen=True, slots=True)
class PersonaEngagementProfile:
    """How one persona engages with product pages.

    Attributes:
        min_views: Fewest product views per category view.
        max_views: Most product views per category view.
        duration_scale: Multiplier applied to the base view duration.
        promotion_weight: Relative appetite for promotion-sourced views.
        brand_weight: Relative appetite for brand-page-sourced views.
        wishlist_adoption: Chance this persona uses the wishlist at all.
    """

    min_views: int
    max_views: int
    duration_scale: float
    promotion_weight: float
    brand_weight: float
    wishlist_adoption: float


#: Per-persona engagement. View counts average close to three overall, which
#: is what the specification asks for; the researcher browses most and longest
#: and the seasonal shopper least, as documented.
PERSONA_ENGAGEMENT_PROFILES: Final[dict[str, PersonaEngagementProfile]] = {
    str(PersonaName.RESEARCHER): PersonaEngagementProfile(
        min_views=2,
        max_views=5,
        duration_scale=1.60,
        promotion_weight=1.0,
        brand_weight=1.0,
        wishlist_adoption=0.16,
    ),
    str(PersonaName.WINDOW_SHOPPER): PersonaEngagementProfile(
        min_views=2,
        max_views=4,
        duration_scale=1.00,
        promotion_weight=1.0,
        brand_weight=1.0,
        wishlist_adoption=0.11,
    ),
    str(PersonaName.BARGAIN_HUNTER): PersonaEngagementProfile(
        min_views=2,
        max_views=4,
        duration_scale=0.90,
        # "Frequently enters from Promotion."
        promotion_weight=3.0,
        brand_weight=0.6,
        wishlist_adoption=0.11,
    ),
    str(PersonaName.LOYAL_CUSTOMER): PersonaEngagementProfile(
        min_views=1,
        max_views=4,
        duration_scale=1.00,
        promotion_weight=0.7,
        # "Frequently returns to familiar brands."
        brand_weight=3.0,
        wishlist_adoption=0.10,
    ),
    str(PersonaName.IMPULSE_BUYER): PersonaEngagementProfile(
        min_views=1,
        max_views=2,
        duration_scale=0.45,
        promotion_weight=1.4,
        brand_weight=0.8,
        wishlist_adoption=0.05,
    ),
    str(PersonaName.SEASONAL_SHOPPER): PersonaEngagementProfile(
        min_views=1,
        max_views=3,
        duration_scale=0.80,
        promotion_weight=1.2,
        brand_weight=0.8,
        wishlist_adoption=0.03,
    ),
}

#: Popularity tiers: (label, share of the catalog, share of views).
POPULARITY_TIERS: Final[tuple[tuple[str, float, float], ...]] = (
    ("HOT", 0.20, 0.70),
    ("WARM", 0.30, 0.20),
    ("COLD", 0.50, 0.10),
)

# Sampling weight per tier. The naive ratio (view share / catalog share) only
# reaches the target distribution when every pool mirrors the catalog. Leaf
# categories hold around eight products, and roughly one pool in six contains
# no popular product at all, which flattens the achieved distribution. These
# weights are calibrated so the *observed* split lands on 70/20/10.
_TIER_WEIGHTS: Final[dict[str, float]] = {"HOT": 6.2, "WARM": 0.50, "COLD": 0.12}

_SOURCES: Final[tuple[ViewSource, ...]] = (
    ViewSource.CATEGORY,
    ViewSource.SEARCH,
    ViewSource.RECOMMENDATION,
    ViewSource.PROMOTION,
    ViewSource.BRAND_PAGE,
)

# Source weights conditioned on whether the category view produced a search.
# Roughly 40% of category views carry a search, so these two rows combine to
# approximately the specified 55/25/10/5/5 marginal split.
_WEIGHTS_WITH_SEARCH: Final[tuple[float, ...]] = (25.0, 60.0, 8.0, 4.0, 3.0)
_WEIGHTS_WITHOUT_SEARCH: Final[tuple[float, ...]] = (73.0, 0.0, 14.0, 7.0, 6.0)

# A right-skewed dwell time: most product pages get a glance, a few get study.
_DURATION_MU: Final[float] = 3.25
_DURATION_SIGMA: Final[float] = 0.90

_SECONDS_AFTER_SEARCH: Final[int] = 1


@dataclass(frozen=True, slots=True)
class ProductCatalog:
    """Products grouped by browsable category with popularity weights.

    Cumulative weights are precomputed per category so that drawing a product
    is a binary search rather than a linear scan - at tens of thousands of
    views over a catalog-wide pool, the difference is the whole runtime.

    Attributes:
        ids_by_category: Category id to the products in its subtree.
        cumulative_by_category: Matching cumulative weight table.
        tier_by_product: Product id to popularity tier label.
    """

    ids_by_category: dict[int, list[int]]
    cumulative_by_category: dict[int, list[float]]
    tier_by_product: dict[int, str]

    @classmethod
    def from_frames(
        cls, categories: pl.DataFrame, products: pl.DataFrame, seed: int
    ) -> ProductCatalog:
        """Build the catalog from the F001 categories and products datasets.

        Args:
            categories: The categories dataset.
            products: The products dataset.
            seed: Run seed, used to assign popularity tiers reproducibly.

        Returns:
            The extracted catalog.

        Raises:
            ValueError: If either dataset is empty, or no product resolves to
                a known category.
        """
        if categories.is_empty():
            raise ValueError("cannot generate product views: the categories dataset is empty")
        if products.is_empty():
            raise ValueError("cannot generate product views: the products dataset is empty")

        category_by_path = dict(
            zip(
                categories["category_path"].to_list(),
                categories["category_id"].to_list(),
                strict=True,
            )
        )
        path_by_category = {category_id: path for path, category_id in category_by_path.items()}

        tier_by_product = cls._assign_tiers(products["product_id"].to_list(), seed)
        weight_by_tier = _TIER_WEIGHTS

        # A product sits in the pool of its own category and every ancestor,
        # so browsing a parent category can surface it.
        pools: dict[int, list[int]] = {}
        weights: dict[int, list[float]] = {}
        for product_id, category_id in zip(
            products["product_id"].to_list(), products["category_id"].to_list(), strict=True
        ):
            path = path_by_category.get(category_id)
            if path is None:
                continue
            weight = weight_by_tier[tier_by_product[product_id]]
            segments = path.split("/")
            for depth in range(1, len(segments) + 1):
                ancestor = category_by_path.get("/".join(segments[:depth]))
                if ancestor is None:
                    continue
                pools.setdefault(ancestor, []).append(product_id)
                weights.setdefault(ancestor, []).append(weight)

        if not pools:
            raise ValueError(
                "cannot generate product views: no product resolves to a known category"
            )

        cumulative = {
            category_id: list(_running_total(values)) for category_id, values in weights.items()
        }
        return cls(
            ids_by_category=pools,
            cumulative_by_category=cumulative,
            tier_by_product=tier_by_product,
        )

    @staticmethod
    def _assign_tiers(product_ids: list[int], seed: int) -> dict[int, str]:
        """Split the catalog into popularity tiers.

        Args:
            product_ids: Every product identifier.
            seed: Run seed.

        Returns:
            Product id to tier label.
        """
        shuffled = list(product_ids)
        random.Random(stream_seed(seed, "product_popularity")).shuffle(shuffled)

        tiers: dict[int, str] = {}
        start = 0
        total = len(shuffled)
        for index, (label, catalog_share, _) in enumerate(POPULARITY_TIERS):
            stop = (
                total
                if index == len(POPULARITY_TIERS) - 1
                else start + int(round(total * catalog_share))
            )
            for product_id in shuffled[start:stop]:
                tiers[product_id] = label
            start = stop
        return tiers

    def has_products(self, category_id: int) -> bool:
        """Return whether a category has any product beneath it.

        Args:
            category_id: The category being browsed.

        Returns:
            ``True`` when at least one product is available.
        """
        return bool(self.ids_by_category.get(category_id))

    def sample(self, rng: random.Random, category_id: int) -> int | None:
        """Draw a product from a category, weighted by popularity.

        Args:
            rng: Random source.
            category_id: The category being browsed.

        Returns:
            A product identifier, or ``None`` when the category is empty.
        """
        ids = self.ids_by_category.get(category_id)
        if not ids:
            return None
        cumulative = self.cumulative_by_category[category_id]
        target = rng.random() * cumulative[-1]
        return ids[bisect.bisect_right(cumulative, target)]


def _running_total(values: list[float]) -> Iterator[float]:
    """Yield the running total of a sequence.

    Args:
        values: Weights in pool order.

    Yields:
        The cumulative total after each weight.
    """
    total = 0.0
    for value in values:
        total += value
        yield total


def persona_engagement_profile(persona_name: str) -> PersonaEngagementProfile:
    """Look up the engagement profile for a persona.

    Args:
        persona_name: Persona name, such as ``"RESEARCHER"``.

    Returns:
        The matching profile.

    Raises:
        KeyError: If the persona has no engagement profile.
    """
    try:
        return PERSONA_ENGAGEMENT_PROFILES[persona_name]
    except KeyError:
        raise KeyError(
            f"Unknown persona: {persona_name!r}. "
            f"Supported personas: {tuple(PERSONA_ENGAGEMENT_PROFILES)}"
        ) from None


def _source_weights(profile: PersonaEngagementProfile, has_search: bool) -> tuple[float, ...]:
    """Return the view source weights for one category view.

    Args:
        profile: The persona's engagement profile.
        has_search: Whether the category view produced a search.

    Returns:
        Weights aligned with :data:`_SOURCES`.
    """
    base = _WEIGHTS_WITH_SEARCH if has_search else _WEIGHTS_WITHOUT_SEARCH
    category, search, recommendation, promotion, brand = base
    return (
        category,
        search,
        recommendation,
        promotion * profile.promotion_weight,
        brand * profile.brand_weight,
    )


def _duration(
    rng: random.Random, profile: PersonaEngagementProfile, config: EngagementConfig
) -> int:
    """Sample how long a product page was open.

    Args:
        rng: Random source.
        profile: The persona's engagement profile.
        config: Global engagement bounds.

    Returns:
        A duration inside the configured band.
    """
    raw = math.exp(rng.gauss(_DURATION_MU, _DURATION_SIGMA)) * profile.duration_scale
    return int(min(config.max_view_seconds, max(config.min_view_seconds, raw)))


def iter_product_view_batches(
    config: EngagementConfig,
    sessions: pl.DataFrame,
    category_views: pl.DataFrame,
    searches: pl.DataFrame,
    catalog: ProductCatalog,
    seed: int,
) -> Iterator[pl.DataFrame]:
    """Yield product views in batches, grouped by session.

    Args:
        config: Engagement configuration.
        sessions: The F003.1 sessions dataset.
        category_views: The F003.2 category views dataset.
        searches: The F003.2 search history dataset.
        catalog: The product catalog with popularity weights.
        seed: Run seed.

    Yields:
        Frames matching the product views schema. A session's views are never
        split across two frames.

    Raises:
        KeyError: If a session names a persona with no engagement profile.
    """
    rng = make_rng(seed, "product_views")

    session_end: dict[int, datetime] = dict(
        zip(
            sessions["session_id"].to_list(),
            sessions["end_time"].to_list(),
            strict=True,
        )
    )
    persona_by_session: dict[int, str] = dict(
        zip(
            sessions["session_id"].to_list(),
            sessions["persona_name"].to_list(),
            strict=True,
        )
    )

    # Searches available to each category view, with the moment they happened.
    searches_by_view: dict[int, list[tuple[int, datetime]]] = {}
    for existing_id, searched_view_id, searched_at in zip(
        searches["search_id"].to_list(),
        searches["category_view_id"].to_list(),
        searches["timestamp"].to_list(),
        strict=True,
    ):
        searches_by_view.setdefault(searched_view_id, []).append((existing_id, searched_at))

    ordered = category_views.sort("session_id", "view_sequence")
    view_ids: list[int] = ordered["category_view_id"].to_list()
    view_sessions: list[int] = ordered["session_id"].to_list()
    view_customers: list[int] = ordered["customer_id"].to_list()
    view_categories: list[int] = ordered["category_id"].to_list()
    view_times: list[datetime] = ordered["timestamp"].to_list()

    product_view_ids: list[int] = []
    batch_sessions: list[int] = []
    batch_customers: list[int] = []
    batch_category_views: list[int] = []
    batch_searches: list[int | None] = []
    batch_categories: list[int] = []
    batch_products: list[int] = []
    sequences: list[int] = []
    sources: list[str] = []
    durations: list[int] = []
    timestamps: list[datetime] = []
    created: list[datetime] = []

    next_product_view_id = 1
    # Rows for the session currently being built, before sequencing.
    pending: list[tuple[datetime, int, int, int, int | None, int, int, str, int]] = []
    current_session: int | None = None

    def flush_session() -> None:
        """Sequence the pending session's views and move them into the batch."""
        nonlocal next_product_view_id
        for sequence, row in enumerate(sorted(pending, key=lambda item: item[0]), start=1):
            (
                moment,
                session_id,
                customer_id,
                category_view_id,
                search_id,
                category_id,
                product_id,
                source,
                duration,
            ) = row
            product_view_ids.append(next_product_view_id)
            batch_sessions.append(session_id)
            batch_customers.append(customer_id)
            batch_category_views.append(category_view_id)
            batch_searches.append(search_id)
            batch_categories.append(category_id)
            batch_products.append(product_id)
            sequences.append(sequence)
            sources.append(source)
            durations.append(duration)
            timestamps.append(moment)
            created.append(moment + timedelta(seconds=duration))
            next_product_view_id += 1
        pending.clear()

    def flush_batch() -> pl.DataFrame:
        """Build a frame from the accumulated rows and reset the buffers."""
        frame = build_frame(
            PRODUCT_VIEWS,
            {
                "product_view_id": product_view_ids,
                "session_id": batch_sessions,
                "customer_id": batch_customers,
                "category_view_id": batch_category_views,
                "search_id": batch_searches,
                "category_id": batch_categories,
                "product_id": batch_products,
                "view_sequence": sequences,
                "view_source": sources,
                "view_duration_seconds": durations,
                "timestamp": timestamps,
                "created_at": created,
            },
        )
        for buffer in (
            product_view_ids,
            batch_sessions,
            batch_customers,
            batch_category_views,
            batch_searches,
            batch_categories,
            batch_products,
            sequences,
            sources,
            durations,
            timestamps,
            created,
        ):
            buffer.clear()
        return frame

    for index, category_view_id in enumerate(view_ids):
        session_id = view_sessions[index]
        if session_id != current_session:
            flush_session()
            if product_view_ids and len(product_view_ids) >= config.batch_size:
                yield flush_batch()
            current_session = session_id

        category_id = view_categories[index]
        if not catalog.has_products(category_id):
            continue

        profile = persona_engagement_profile(persona_by_session[session_id])
        available = searches_by_view.get(category_view_id, [])
        weights = _source_weights(profile, bool(available))
        ends_at = session_end[session_id]

        count = max(
            config.min_product_views,
            min(
                rng.randint(profile.min_views, profile.max_views),
                config.max_product_views,
            ),
        )
        # Leave room for the shortest possible view before the session ends.
        # A category view always ends inside its session, so this is never
        # earlier than the category view itself.
        latest = ends_at - timedelta(seconds=config.min_view_seconds)

        for _ in range(count):
            source = rng.choices(_SOURCES, weights=weights, k=1)[0]
            search_id: int | None = None
            earliest = view_times[index]
            if source is ViewSource.SEARCH and available:
                candidate_id, search_moment = rng.choice(available)
                after_search = search_moment + timedelta(seconds=_SECONDS_AFTER_SEARCH)
                if after_search <= latest:
                    search_id, earliest = candidate_id, max(earliest, after_search)
                else:
                    # No room left after that search; this view came from the
                    # category page instead.
                    source = ViewSource.CATEGORY

            product_id = catalog.sample(rng, category_id)
            if product_id is None:  # pragma: no cover - guarded by has_products
                continue

            if latest <= earliest:
                moment = earliest
            else:
                span = int((latest - earliest).total_seconds())
                moment = earliest + timedelta(seconds=rng.randrange(span + 1))

            remaining = int((ends_at - moment).total_seconds())
            duration = min(_duration(rng, profile, config), max(config.min_view_seconds, remaining))

            pending.append(
                (
                    moment,
                    session_id,
                    view_customers[index],
                    category_view_id,
                    search_id,
                    category_id,
                    product_id,
                    str(source),
                    duration,
                )
            )

    flush_session()
    if product_view_ids:
        yield flush_batch()


def generate_product_views(
    config: EngagementConfig,
    sessions: pl.DataFrame,
    category_views: pl.DataFrame,
    searches: pl.DataFrame,
    catalog: ProductCatalog,
    seed: int,
) -> pl.DataFrame:
    """Generate the complete product views dataset.

    Args:
        config: Engagement configuration.
        sessions: The F003.1 sessions dataset.
        category_views: The F003.2 category views dataset.
        searches: The F003.2 search history dataset.
        catalog: The product catalog with popularity weights.
        seed: Run seed.

    Returns:
        One row per product page opened, keyed by sequential
        ``product_view_id``.

    Raises:
        KeyError: If a session names a persona with no engagement profile.
    """
    batches = list(
        iter_product_view_batches(config, sessions, category_views, searches, catalog, seed)
    )
    return pl.concat(batches, how="vertical") if batches else empty_frame(PRODUCT_VIEWS)
