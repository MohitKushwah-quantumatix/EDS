"""Generator for the product category tree.

The tree is built breadth-first from curated retail category names so that
paths such as ``Electronics/Computers/Laptops`` are recognisable. Only leaf
categories carry products, which is how real merchandising hierarchies work.
"""

from __future__ import annotations

from typing import Final

import polars as pl

from eds.config import MasterDataConfig
from eds.core.frames import build_frame, format_code
from eds.domains.retail.domain.catalog.schema import CATEGORIES

__all__ = ["ROOT_CATEGORY_NAMES", "generate_categories", "leaf_category_roots"]

ROOT_CATEGORY_NAMES: Final[tuple[str, ...]] = (
    "Electronics",
    "Home & Kitchen",
    "Clothing",
    "Sports & Outdoors",
    "Health & Beauty",
    "Toys & Games",
    "Grocery",
    "Automotive",
    "Books & Media",
    "Office Products",
    "Pet Supplies",
    "Garden & Outdoor",
    "Furniture",
    "Computers",
)

_SUBCATEGORIES: Final[dict[str, tuple[str, ...]]] = {
    "Electronics": ("Televisions", "Audio", "Cameras", "Wearables", "Smart Home", "Phones"),
    "Home & Kitchen": ("Cookware", "Small Appliances", "Bedding", "Storage", "Decor", "Lighting"),
    "Clothing": (
        "Menswear",
        "Womenswear",
        "Childrenswear",
        "Footwear",
        "Accessories",
        "Activewear",
    ),
    "Sports & Outdoors": (
        "Fitness",
        "Cycling",
        "Camping",
        "Water Sports",
        "Team Sports",
        "Hunting",
    ),
    "Health & Beauty": ("Skincare", "Haircare", "Vitamins", "Oral Care", "Fragrance", "Cosmetics"),
    "Toys & Games": ("Board Games", "Building Sets", "Dolls", "Outdoor Play", "Puzzles", "Figures"),
    "Grocery": ("Beverages", "Snacks", "Pantry", "Frozen", "Dairy", "Bakery"),
    "Automotive": ("Car Care", "Interior", "Exterior", "Tools", "Tyres", "Electronics"),
    "Books & Media": ("Fiction", "Non Fiction", "Children", "Music", "Film", "Magazines"),
    "Office Products": ("Paper", "Writing", "Filing", "Printers", "Furniture", "Supplies"),
    "Pet Supplies": ("Dog", "Cat", "Small Animal", "Aquatic", "Bird", "Grooming"),
    "Garden & Outdoor": ("Plants", "Tools", "Furniture", "Grills", "Watering", "Decor"),
    "Furniture": ("Living Room", "Bedroom", "Dining", "Office", "Outdoor", "Storage"),
    "Computers": ("Laptops", "Desktops", "Monitors", "Components", "Networking", "Storage"),
}

_LEAF_MODIFIERS: Final[tuple[str, ...]] = (
    "Essentials",
    "Premium",
    "Value",
    "Professional",
    "Accessories",
    "Bundles",
)


def _root_name(index: int) -> str:
    """Return the name of the level-1 category at ``index``.

    Args:
        index: Zero-based root index.

    Returns:
        A curated name, or a generated one once the curated list is exhausted.
    """
    if index < len(ROOT_CATEGORY_NAMES):
        return ROOT_CATEGORY_NAMES[index]
    return f"General Merchandise {index - len(ROOT_CATEGORY_NAMES) + 1}"


def _child_name(parent_name: str, root_name: str, level: int, index: int) -> str:
    """Return the name of a child category.

    Args:
        parent_name: Name of the parent category.
        root_name: Name of the level-1 ancestor.
        level: Level of the child being named, 2 or deeper.
        index: Zero-based index of the child within its parent.

    Returns:
        A curated subcategory name where one is available, otherwise a
        modifier applied to the parent name.
    """
    if level == 2:
        pool = _SUBCATEGORIES.get(root_name, ())
        if index < len(pool):
            return pool[index]
        return f"{root_name} Group {index + 1}"
    if index < len(_LEAF_MODIFIERS):
        return f"{parent_name} {_LEAF_MODIFIERS[index]}"
    return f"{parent_name} Range {index + 1}"


def generate_categories(config: MasterDataConfig) -> pl.DataFrame:
    """Generate the category tree.

    Args:
        config: Master data configuration supplying the tree shape.

    Returns:
        One row per category, ordered breadth-first and keyed by sequential
        ``category_id``. Level-1 categories have a null ``parent_category_id``.
    """
    category_ids: list[int] = []
    parent_ids: list[int | None] = []
    codes: list[str] = []
    names: list[str] = []
    paths: list[str] = []
    levels: list[int] = []
    leaf_flags: list[bool] = []

    next_id = 1
    # Each frontier entry is (category_id, name, path, root_name).
    frontier: list[tuple[int, str, str, str]] = []

    for index in range(config.root_categories):
        name = _root_name(index)
        category_ids.append(next_id)
        parent_ids.append(None)
        codes.append(format_code("CAT", next_id))
        names.append(name)
        paths.append(name)
        levels.append(1)
        leaf_flags.append(config.category_depth == 1)
        frontier.append((next_id, name, name, name))
        next_id += 1

    for level in range(2, config.category_depth + 1):
        next_frontier: list[tuple[int, str, str, str]] = []
        is_leaf_level = level == config.category_depth
        for parent_id, parent_name, parent_path, root_name in frontier:
            for index in range(config.children_per_category):
                name = _child_name(parent_name, root_name, level, index)
                path = f"{parent_path}/{name}"
                category_ids.append(next_id)
                parent_ids.append(parent_id)
                codes.append(format_code("CAT", next_id))
                names.append(name)
                paths.append(path)
                levels.append(level)
                leaf_flags.append(is_leaf_level)
                next_frontier.append((next_id, name, path, root_name))
                next_id += 1
        frontier = next_frontier

    return build_frame(
        CATEGORIES,
        {
            "category_id": category_ids,
            "parent_category_id": parent_ids,
            "category_code": codes,
            "category_name": names,
            "category_path": paths,
            "level": levels,
            "is_leaf": leaf_flags,
        },
    )


def leaf_category_roots(categories: pl.DataFrame) -> dict[int, str]:
    """Map each leaf category id to its level-1 ancestor name.

    Product pricing is driven by the top-level category, so this lookup lets
    the product generator find the right price band from a leaf id.

    Args:
        categories: The generated categories dataset.

    Returns:
        A mapping of leaf ``category_id`` to root category name.
    """
    leaves = categories.filter(pl.col("is_leaf").cast(pl.Boolean))
    ids: list[int] = leaves["category_id"].to_list()
    paths: list[str] = leaves["category_path"].to_list()
    return {
        category_id: path.split("/", 1)[0] for category_id, path in zip(ids, paths, strict=True)
    }
