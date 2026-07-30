"""Deterministic random number streams for reference-data generation.

Every generator draws from its own named stream derived from the run seed.
Independent streams matter for two reasons:

* Adding or resizing one dataset does not shift the values of any other.
* Generators can run in any order and still reproduce byte-identical output.

A stream seed is the first 8 bytes of ``sha256(f"{seed}:{stream}")``, which is
stable across processes and Python versions - unlike :func:`hash`.
"""

from __future__ import annotations

import hashlib
import random
import secrets
from typing import Final

from faker import Faker

__all__ = ["make_faker", "make_rng", "resolve_seed", "stream_seed"]

_SEED_BYTES: Final[int] = 8


def resolve_seed(seed: int | None) -> int:
    """Return a concrete seed, drawing entropy when the run is non-deterministic.

    Args:
        seed: Configured seed, or ``None`` for a non-deterministic run.

    Returns:
        ``seed`` unchanged, or a fresh random seed when ``seed`` is ``None``.
    """
    if seed is not None:
        return seed
    return secrets.randbits(_SEED_BYTES * 8)


def stream_seed(seed: int, stream: str) -> int:
    """Derive a reproducible seed for a named stream.

    Args:
        seed: The run seed.
        stream: Stream name, such as ``"products"``.

    Returns:
        A seed unique to the ``(seed, stream)`` pair.

    Raises:
        ValueError: If ``stream`` is empty.
    """
    if not stream:
        raise ValueError("stream name must not be empty")
    digest = hashlib.sha256(f"{seed}:{stream}".encode()).digest()
    return int.from_bytes(digest[:_SEED_BYTES], "big")


def make_rng(seed: int, stream: str) -> random.Random:
    """Create an independent random generator for a named stream.

    Args:
        seed: The run seed.
        stream: Stream name.

    Returns:
        A seeded :class:`random.Random` instance.

    Raises:
        ValueError: If ``stream`` is empty.
    """
    return random.Random(stream_seed(seed, stream))


def make_faker(seed: int, stream: str, locale: str = "en_US") -> Faker:
    """Create an independently seeded Faker instance for a named stream.

    Args:
        seed: The run seed.
        stream: Stream name.
        locale: Faker locale.

    Returns:
        A Faker instance seeded for this stream.

    Raises:
        ValueError: If ``stream`` is empty.
    """
    faker = Faker(locale)
    faker.seed_instance(stream_seed(seed, stream))
    return faker
