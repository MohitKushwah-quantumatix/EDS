"""Generator for the search history dataset.

Every search is attached to a category view and inherits that view's category,
so a search is always about the section the customer is standing in. Search
text is drawn from a curated vocabulary keyed by top-level category, which is
what keeps "Electronics -> Coffee Table" from ever being generated.

Search timestamps fall inside the window of the view they belong to, which
places them after the first category view and inside the session by
construction.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

import polars as pl

from eds.config import BrowsingConfig
from eds.core.frames import build_frame, empty_frame
from eds.core.random_streams import make_rng
from eds.domains.retail.domain.journey.enums import PersonaName
from eds.domains.retail.domain.journey.schema import SEARCH_HISTORY
from eds.domains.retail.generators.journey.category_generator import CategoryCatalog

__all__ = [
    "CATEGORY_SEARCH_TERMS",
    "PERSONA_SEARCH_RANGES",
    "generate_searches",
    "iter_search_batches",
    "search_terms_for_root",
]

# Product-oriented search phrases per top-level category. The first five
# groups are the vocabularies named in the specification; the rest cover the
# remaining F001 top-level categories so that every browsable section can
# produce a relevant search.
CATEGORY_SEARCH_TERMS: Final[dict[str, tuple[str, ...]]] = {
    "Electronics": (
        "Gaming Laptop",
        "Wireless Mouse",
        "Mechanical Keyboard",
        "Bluetooth Speaker",
        "USB-C Charger",
        "Noise Cancelling Headphones",
        "Smart Watch",
        "4K Television",
        "Action Camera",
        "Power Bank",
    ),
    "Furniture": (
        "Office Chair",
        "Standing Desk",
        "Coffee Table",
        "Bookshelf",
        "Sofa Bed",
        "Dining Chair",
        "Wardrobe",
        "Bedside Table",
    ),
    "Clothing": (
        "Running Shoes",
        "T-Shirt",
        "Jeans",
        "Sneakers",
        "Jacket",
        "Winter Coat",
        "Leather Wallet",
        "Wool Scarf",
        "Formal Shirt",
    ),
    "Home & Kitchen": (
        "Coffee Machine",
        "Mixer Grinder",
        "Cookware Set",
        "Water Bottle",
        "Dining Table",
        "Air Fryer",
        "Knife Set",
        "Storage Jars",
        "Bed Sheets",
    ),
    "Sports & Outdoors": (
        "Cricket Bat",
        "Football",
        "Tennis Racket",
        "Gym Bag",
        "Yoga Mat",
        "Camping Tent",
        "Cycling Helmet",
        "Dumbbell Set",
        "Hiking Boots",
    ),
    "Computers": (
        "Gaming Laptop",
        "Ultrawide Monitor",
        "External SSD",
        "Graphics Card",
        "Wireless Router",
        "Laptop Stand",
        "Docking Station",
        "Desktop Tower",
    ),
    "Health & Beauty": (
        "Face Serum",
        "Sunscreen",
        "Hair Dryer",
        "Electric Toothbrush",
        "Vitamin C Tablets",
        "Shampoo",
        "Moisturiser",
        "Perfume",
    ),
    "Toys & Games": (
        "Board Game",
        "Building Blocks",
        "Jigsaw Puzzle",
        "Remote Control Car",
        "Action Figure",
        "Soft Toy",
        "Card Game",
    ),
    "Grocery": (
        "Olive Oil",
        "Ground Coffee",
        "Green Tea",
        "Breakfast Cereal",
        "Dark Chocolate",
        "Basmati Rice",
        "Protein Bars",
    ),
    "Automotive": (
        "Car Vacuum",
        "Dash Camera",
        "Wiper Blades",
        "Car Phone Mount",
        "Engine Oil",
        "Tyre Inflator",
        "Seat Covers",
    ),
    "Books & Media": (
        "Crime Novel",
        "Cookbook",
        "Vinyl Record",
        "Childrens Books",
        "Travel Guide",
        "Biography",
        "Graphic Novel",
    ),
    "Office Products": (
        "Printer Paper",
        "Fountain Pen",
        "Filing Cabinet",
        "Desk Lamp",
        "Laser Printer",
        "Notebook",
        "Whiteboard",
    ),
    "Pet Supplies": (
        "Dog Food",
        "Cat Litter",
        "Pet Bed",
        "Dog Lead",
        "Aquarium Filter",
        "Bird Cage",
        "Grooming Brush",
    ),
    "Garden & Outdoor": (
        "Garden Hose",
        "Lawn Mower",
        "Patio Set",
        "Charcoal Grill",
        "Plant Pots",
        "Pruning Shears",
        "Bird Feeder",
    ),
}

# Fallback for a top-level category with no curated vocabulary. Kept generic
# and product-oriented rather than random.
_DEFAULT_SEARCH_TERMS: Final[tuple[str, ...]] = (
    "Gift Set",
    "Best Sellers",
    "New Arrivals",
    "Storage Box",
    "Travel Kit",
)

# Qualifiers keep phrases within one to four words while adding variety.
_QUALIFIERS: Final[tuple[str, ...]] = (
    "Best",
    "Cheap",
    "Premium",
    "Portable",
    "Wireless",
    "Compact",
    "Black",
)
_QUALIFIER_PROBABILITY: Final[float] = 0.3
_MAX_SEARCH_WORDS: Final[int] = 4

#: Searches per session by persona. Bargain hunters and researchers search
#: extensively; impulse buyers barely search at all.
PERSONA_SEARCH_RANGES: Final[dict[str, tuple[int, int]]] = {
    str(PersonaName.BARGAIN_HUNTER): (3, 6),
    str(PersonaName.RESEARCHER): (2, 5),
    str(PersonaName.WINDOW_SHOPPER): (0, 3),
    str(PersonaName.LOYAL_CUSTOMER): (0, 2),
    str(PersonaName.SEASONAL_SHOPPER): (0, 2),
    str(PersonaName.IMPULSE_BUYER): (0, 1),
}


@dataclass(frozen=True, slots=True)
class _View:
    """One category view a search can be attached to."""

    view_id: int
    category_id: int
    timestamp: datetime
    duration: int


def search_terms_for_root(root_name: str) -> tuple[str, ...]:
    """Return the search vocabulary for a top-level category.

    Args:
        root_name: Level-1 category name.

    Returns:
        The curated phrases, or a generic product-oriented fallback when the
        category has no vocabulary of its own.
    """
    return CATEGORY_SEARCH_TERMS.get(root_name, _DEFAULT_SEARCH_TERMS)


def _search_text(rng: random.Random, root_name: str) -> str:
    """Compose a realistic search phrase for a category.

    Args:
        rng: Random source.
        root_name: Level-1 category name the customer is browsing.

    Returns:
        A phrase of one to four words drawn from the category's vocabulary.
    """
    phrase = rng.choice(search_terms_for_root(root_name))
    if rng.random() < _QUALIFIER_PROBABILITY:
        candidate = f"{rng.choice(_QUALIFIERS)} {phrase}"
        if len(candidate.split()) <= _MAX_SEARCH_WORDS:
            return candidate
    return phrase


def _search_count(rng: random.Random, persona_name: str, config: BrowsingConfig) -> int:
    """Decide how many searches a session performs.

    Args:
        rng: Random source.
        persona_name: The session's persona.
        config: Global browsing bounds.

    Returns:
        A count within both the persona range and the configured bounds.
    """
    low, high = PERSONA_SEARCH_RANGES.get(persona_name, (0, 2))
    drawn = rng.randint(low, high)
    return max(config.min_searches, min(drawn, config.max_searches))


def _results_count(rng: random.Random, config: BrowsingConfig) -> int:
    """Sample how many results a search returned.

    Args:
        rng: Random source.
        config: Global browsing bounds.

    Returns:
        Zero for a search that found nothing, otherwise a positive count.
    """
    if rng.random() < config.no_results_rate:
        return 0
    return rng.randint(1, config.max_results_count)


def iter_search_batches(
    config: BrowsingConfig,
    sessions: pl.DataFrame,
    category_views: pl.DataFrame,
    catalog: CategoryCatalog,
    seed: int,
) -> Iterator[pl.DataFrame]:
    """Yield searches in batches, grouped by session.

    Args:
        config: Browsing configuration.
        sessions: The F003.1 sessions dataset.
        category_views: The generated category views dataset.
        catalog: The browsable category catalog, used to resolve vocabularies.
        seed: Run seed.

    Yields:
        Frames matching the search history schema.
    """
    rng = make_rng(seed, "search_history")

    views_by_session: dict[int, list[_View]] = {}
    for view_id, session_id, category_id, timestamp, duration in zip(
        category_views["category_view_id"].to_list(),
        category_views["session_id"].to_list(),
        category_views["category_id"].to_list(),
        category_views["timestamp"].to_list(),
        category_views["duration_seconds"].to_list(),
        strict=True,
    ):
        views_by_session.setdefault(session_id, []).append(
            _View(view_id, category_id, timestamp, duration)
        )

    session_ids: list[int] = sessions["session_id"].to_list()
    customer_ids: list[int] = sessions["customer_id"].to_list()
    persona_names: list[str] = sessions["persona_name"].to_list()
    bounces: list[bool] = sessions["bounce"].to_list()

    search_ids: list[int] = []
    batch_session_ids: list[int] = []
    batch_customer_ids: list[int] = []
    view_ids: list[int] = []
    category_ids: list[int] = []
    sequences: list[int] = []
    texts: list[str] = []
    results: list[int] = []
    clicked: list[bool] = []
    timestamps: list[datetime] = []
    created: list[datetime] = []

    next_search_id = 1

    def flush() -> pl.DataFrame:
        """Build a frame from the accumulated rows and reset the buffers."""
        frame = build_frame(
            SEARCH_HISTORY,
            {
                "search_id": search_ids,
                "session_id": batch_session_ids,
                "customer_id": batch_customer_ids,
                "category_view_id": view_ids,
                "category_id": category_ids,
                "search_sequence": sequences,
                "search_text": texts,
                "results_count": results,
                "clicked_result": clicked,
                "timestamp": timestamps,
                "created_at": created,
            },
        )
        for buffer in (
            search_ids,
            batch_session_ids,
            batch_customer_ids,
            view_ids,
            category_ids,
            sequences,
            texts,
            results,
            clicked,
            timestamps,
            created,
        ):
            buffer.clear()
        return frame

    for index, session_id in enumerate(session_ids):
        # A bounce viewed a single page and left; it did not search.
        if bounces[index]:
            continue

        views = views_by_session.get(session_id)
        if not views:
            continue

        count = _search_count(rng, persona_names[index], config)
        if count == 0:
            continue

        # Attach each search to a view, then order them by time so the
        # sequence numbers read chronologically.
        attached = [rng.choice(views) for _ in range(count)]
        moments = [
            (view, view.timestamp + timedelta(seconds=rng.randint(1, view.duration)))
            for view in attached
        ]
        moments.sort(key=lambda pair: pair[1])

        for sequence, (view, moment) in enumerate(moments, start=1):
            found = _results_count(rng, config)

            search_ids.append(next_search_id)
            batch_session_ids.append(session_id)
            batch_customer_ids.append(customer_ids[index])
            view_ids.append(view.view_id)
            category_ids.append(view.category_id)
            sequences.append(sequence)
            texts.append(_search_text(rng, catalog.root_of(view.category_id)))
            results.append(found)
            # A search that found nothing cannot have been clicked.
            clicked.append(found > 0 and rng.random() < config.click_through_rate)
            timestamps.append(moment)
            created.append(moment)
            next_search_id += 1

        if len(search_ids) >= config.batch_size:
            yield flush()

    if search_ids:
        yield flush()


def generate_searches(
    config: BrowsingConfig,
    sessions: pl.DataFrame,
    category_views: pl.DataFrame,
    catalog: CategoryCatalog,
    seed: int,
) -> pl.DataFrame:
    """Generate the complete search history dataset.

    Args:
        config: Browsing configuration.
        sessions: The F003.1 sessions dataset.
        category_views: The generated category views dataset.
        catalog: The browsable category catalog.
        seed: Run seed.

    Returns:
        Zero or more rows per session, keyed by sequential ``search_id``.
    """
    batches = list(iter_search_batches(config, sessions, category_views, catalog, seed))
    return pl.concat(batches, how="vertical") if batches else empty_frame(SEARCH_HISTORY)
