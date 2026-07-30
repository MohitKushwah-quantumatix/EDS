"""Generator for the category views dataset.

Every session produces at least one category view. How many, and how long each
lasts, follows the session's persona - a researcher works through many
categories slowly, an impulse buyer glances at one or two.

Two constraints tie this feature to F003.1 rather than letting it drift:

* A **bounce** session viewed one page, so it produces exactly one category
  view.
* Views always fit inside the session's own duration, and the first view's
  entry method is inherited from where the session landed.

Browsing is modelled as walking around a section of the catalog: after the
first category, later views usually stay under the same top-level category
rather than jumping across the store at random.
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
from eds.domains.retail.domain.journey.enums import EntryMethod, LandingPage, PersonaName
from eds.domains.retail.domain.journey.schema import CATEGORY_VIEWS

__all__ = [
    "PERSONA_VIEW_PROFILES",
    "CategoryCatalog",
    "PersonaViewProfile",
    "generate_category_views",
    "iter_category_view_batches",
    "persona_view_profile",
]


@dataclass(frozen=True, slots=True)
class PersonaViewProfile:
    """How one persona browses categories.

    Attributes:
        min_views: Fewest category views in a non-bounce session.
        max_views: Most category views in a non-bounce session.
        min_seconds: Shortest time on a category page.
        max_seconds: Longest time on a category page.
        entry_weights: Relative frequency of each entry method after the
            first view.
    """

    min_views: int
    max_views: int
    min_seconds: int
    max_seconds: int
    entry_weights: tuple[int, ...]


_ENTRY_METHODS: Final[tuple[EntryMethod, ...]] = (
    EntryMethod.HOMEPAGE,
    EntryMethod.NAVIGATION_MENU,
    EntryMethod.PROMOTION_BANNER,
    EntryMethod.SEARCH_RESULT,
    EntryMethod.RECOMMENDATION,
    EntryMethod.BRAND_PAGE,
)

# Weights are ordered as _ENTRY_METHODS. Bargain hunters favour promotion
# banners and loyal customers return through the homepage, as specified.
PERSONA_VIEW_PROFILES: Final[dict[str, PersonaViewProfile]] = {
    str(PersonaName.RESEARCHER): PersonaViewProfile(
        min_views=6,
        max_views=10,
        min_seconds=45,
        max_seconds=180,
        entry_weights=(10, 34, 8, 24, 16, 8),
    ),
    str(PersonaName.WINDOW_SHOPPER): PersonaViewProfile(
        min_views=5,
        max_views=8,
        min_seconds=20,
        max_seconds=110,
        entry_weights=(18, 30, 16, 12, 18, 6),
    ),
    str(PersonaName.BARGAIN_HUNTER): PersonaViewProfile(
        min_views=4,
        max_views=7,
        min_seconds=15,
        max_seconds=95,
        entry_weights=(8, 18, 45, 18, 7, 4),
    ),
    str(PersonaName.LOYAL_CUSTOMER): PersonaViewProfile(
        min_views=3,
        max_views=6,
        min_seconds=15,
        max_seconds=85,
        entry_weights=(45, 22, 8, 8, 13, 4),
    ),
    str(PersonaName.IMPULSE_BUYER): PersonaViewProfile(
        min_views=1,
        max_views=3,
        min_seconds=5,
        max_seconds=35,
        entry_weights=(16, 18, 26, 12, 24, 4),
    ),
    str(PersonaName.SEASONAL_SHOPPER): PersonaViewProfile(
        min_views=1,
        max_views=4,
        min_seconds=10,
        max_seconds=70,
        entry_weights=(20, 24, 30, 12, 10, 4),
    ),
}

# The first view's entry method is inherited from where the session landed,
# so F003.1 and F003.2 agree about how the visit began.
_ENTRY_BY_LANDING: Final[dict[str, EntryMethod]] = {
    str(LandingPage.HOMEPAGE): EntryMethod.HOMEPAGE,
    str(LandingPage.CATEGORY): EntryMethod.NAVIGATION_MENU,
    str(LandingPage.SEARCH): EntryMethod.SEARCH_RESULT,
    str(LandingPage.PROMOTION): EntryMethod.PROMOTION_BANNER,
    str(LandingPage.BRAND): EntryMethod.BRAND_PAGE,
    str(LandingPage.CAMPAIGN): EntryMethod.PROMOTION_BANNER,
}

# Probability that the next category shares the current top-level category.
_SAME_SECTION_PROBABILITY: Final[float] = 0.65


@dataclass(frozen=True, slots=True)
class CategoryCatalog:
    """The browsable categories, grouped by top-level section.

    Attributes:
        category_ids: Every category identifier.
        root_by_category: Category id to its level-1 ancestor name.
        ids_by_root: Level-1 ancestor name to the categories beneath it.
    """

    category_ids: list[int]
    root_by_category: dict[int, str]
    ids_by_root: dict[str, list[int]]

    @classmethod
    def from_frame(cls, categories: pl.DataFrame) -> CategoryCatalog:
        """Build the catalog from the F001 categories dataset.

        Args:
            categories: The categories dataset.

        Returns:
            The extracted catalog.

        Raises:
            ValueError: If the dataset is empty, leaving nothing to browse.
        """
        if categories.is_empty():
            raise ValueError("cannot generate category views: the categories dataset is empty")

        ids: list[int] = categories["category_id"].to_list()
        paths: list[str] = categories["category_path"].to_list()
        root_by_category = {
            category_id: path.split("/", 1)[0] for category_id, path in zip(ids, paths, strict=True)
        }

        ids_by_root: dict[str, list[int]] = {}
        for category_id, root in root_by_category.items():
            ids_by_root.setdefault(root, []).append(category_id)

        return cls(category_ids=ids, root_by_category=root_by_category, ids_by_root=ids_by_root)

    def root_of(self, category_id: int) -> str:
        """Return the level-1 ancestor name of a category.

        Args:
            category_id: The category.

        Returns:
            The top-level category name.

        Raises:
            KeyError: If the category is not in the catalog.
        """
        return self.root_by_category[category_id]


def persona_view_profile(persona_name: str) -> PersonaViewProfile:
    """Look up the browsing profile for a persona.

    Args:
        persona_name: Persona name, such as ``"RESEARCHER"``.

    Returns:
        The matching profile.

    Raises:
        KeyError: If the persona has no browsing profile.
    """
    try:
        return PERSONA_VIEW_PROFILES[persona_name]
    except KeyError:
        raise KeyError(
            f"Unknown persona: {persona_name!r}. Supported personas: {tuple(PERSONA_VIEW_PROFILES)}"
        ) from None


def _view_count(
    rng: random.Random,
    profile: PersonaViewProfile,
    config: BrowsingConfig,
    bounce: bool,
    duration_seconds: int,
) -> int:
    """Decide how many categories a session visits.

    The only hard ceiling beyond the persona range is time: every view needs
    at least ``min_view_seconds``, so a short session cannot hold many views.

    Args:
        rng: Random source.
        profile: The persona's browsing profile.
        config: Global browsing bounds.
        bounce: Whether the session bounced.
        duration_seconds: How long the session lasted.

    Returns:
        A count of at least one, bounded by the persona, the configured
        maximum, and the time available.
    """
    if bounce:
        return config.min_category_views

    drawn = rng.randint(profile.min_views, profile.max_views)
    affordable = duration_seconds // config.min_view_seconds
    return max(
        config.min_category_views,
        min(drawn, config.max_category_views, affordable),
    )


def _view_durations(
    rng: random.Random,
    count: int,
    profile: PersonaViewProfile,
    config: BrowsingConfig,
    session_seconds: int,
) -> list[int]:
    """Split the session's time across its category views.

    Each view keeps at least the configured minimum, and the views together
    never outlast the session that contains them.

    Args:
        rng: Random source.
        count: Number of views.
        profile: The persona's browsing profile.
        config: Global browsing bounds.
        session_seconds: The session's total duration.

    Returns:
        One duration per view, in view order.
    """
    lowest = config.min_view_seconds
    highest = min(config.max_view_seconds, profile.max_seconds)
    preferred_low = max(lowest, min(profile.min_seconds, highest))

    durations: list[int] = []
    remaining = session_seconds
    for index in range(count):
        views_left = count - index - 1
        # Reserve the minimum for every view still to come.
        ceiling = min(highest, remaining - lowest * views_left)
        ceiling = max(lowest, ceiling)
        floor = min(preferred_low, ceiling)
        duration = rng.randint(floor, ceiling)
        durations.append(duration)
        remaining -= duration
    return durations


def iter_category_view_batches(
    config: BrowsingConfig,
    sessions: pl.DataFrame,
    catalog: CategoryCatalog,
    seed: int,
) -> Iterator[pl.DataFrame]:
    """Yield category views in batches, grouped by session.

    Args:
        config: Browsing configuration.
        sessions: The F003.1 sessions dataset.
        catalog: The browsable category catalog.
        seed: Run seed.

    Yields:
        Frames matching the category views schema. A session's views are never
        split across two frames.

    Raises:
        KeyError: If a session names a persona with no browsing profile.
    """
    rng = make_rng(seed, "category_views")

    session_ids: list[int] = sessions["session_id"].to_list()
    customer_ids: list[int] = sessions["customer_id"].to_list()
    persona_names: list[str] = sessions["persona_name"].to_list()
    landing_pages: list[str] = sessions["landing_page"].to_list()
    starts: list[datetime] = sessions["start_time"].to_list()
    session_durations: list[int] = sessions["duration_seconds"].to_list()
    bounces: list[bool] = sessions["bounce"].to_list()

    view_ids: list[int] = []
    batch_session_ids: list[int] = []
    batch_customer_ids: list[int] = []
    category_ids: list[int] = []
    sequences: list[int] = []
    entry_methods: list[str] = []
    timestamps: list[datetime] = []
    durations: list[int] = []
    created: list[datetime] = []

    next_view_id = 1

    def flush() -> pl.DataFrame:
        """Build a frame from the accumulated rows and reset the buffers."""
        frame = build_frame(
            CATEGORY_VIEWS,
            {
                "category_view_id": view_ids,
                "session_id": batch_session_ids,
                "customer_id": batch_customer_ids,
                "category_id": category_ids,
                "view_sequence": sequences,
                "entry_method": entry_methods,
                "timestamp": timestamps,
                "duration_seconds": durations,
                "created_at": created,
            },
        )
        for buffer in (
            view_ids,
            batch_session_ids,
            batch_customer_ids,
            category_ids,
            sequences,
            entry_methods,
            timestamps,
            durations,
            created,
        ):
            buffer.clear()
        return frame

    for index, session_id in enumerate(session_ids):
        profile = persona_view_profile(persona_names[index])
        count = _view_count(rng, profile, config, bounces[index], session_durations[index])
        view_durations = _view_durations(rng, count, profile, config, session_durations[index])

        offset = 0
        current_category = rng.choice(catalog.category_ids)
        for sequence, duration in enumerate(view_durations, start=1):
            if sequence == 1:
                entry = _ENTRY_BY_LANDING.get(landing_pages[index], EntryMethod.NAVIGATION_MENU)
            else:
                entry = rng.choices(_ENTRY_METHODS, weights=profile.entry_weights, k=1)[0]
                # Usually keep browsing the same section of the catalog.
                if rng.random() < _SAME_SECTION_PROBABILITY:
                    section = catalog.ids_by_root[catalog.root_of(current_category)]
                    current_category = rng.choice(section)
                else:
                    current_category = rng.choice(catalog.category_ids)

            timestamp = starts[index] + timedelta(seconds=offset)

            view_ids.append(next_view_id)
            batch_session_ids.append(session_id)
            batch_customer_ids.append(customer_ids[index])
            category_ids.append(current_category)
            sequences.append(sequence)
            entry_methods.append(str(entry))
            timestamps.append(timestamp)
            durations.append(duration)
            created.append(timestamp + timedelta(seconds=duration))

            offset += duration
            next_view_id += 1

        if len(view_ids) >= config.batch_size:
            yield flush()

    if view_ids:
        yield flush()


def generate_category_views(
    config: BrowsingConfig,
    sessions: pl.DataFrame,
    catalog: CategoryCatalog,
    seed: int,
) -> pl.DataFrame:
    """Generate the complete category views dataset.

    Args:
        config: Browsing configuration.
        sessions: The F003.1 sessions dataset.
        catalog: The browsable category catalog.
        seed: Run seed.

    Returns:
        At least one row per session, keyed by sequential
        ``category_view_id``.

    Raises:
        KeyError: If a session names a persona with no browsing profile.
    """
    batches = list(iter_category_view_batches(config, sessions, catalog, seed))
    return pl.concat(batches, how="vertical") if batches else empty_frame(CATEGORY_VIEWS)
