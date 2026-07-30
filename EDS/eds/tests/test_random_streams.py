"""Tests for the deterministic random stream helpers."""

from __future__ import annotations

import pytest

from eds.generators.random_streams import make_faker, make_rng, resolve_seed, stream_seed


def test_same_seed_and_stream_give_the_same_values() -> None:
    """A stream is reproducible across separate generator instances."""
    first = [make_rng(7, "products").random() for _ in range(3)]
    second = [make_rng(7, "products").random() for _ in range(3)]

    assert first == second


def test_different_streams_diverge() -> None:
    """Independent streams do not produce the same sequence."""
    products = make_rng(7, "products").random()
    brands = make_rng(7, "brands").random()

    assert products != brands


def test_different_seeds_diverge() -> None:
    """Changing the run seed changes the stream."""
    assert make_rng(1, "products").random() != make_rng(2, "products").random()


def test_stream_seed_is_stable_across_processes() -> None:
    """The derived seed is a fixed function, not a salted hash."""
    assert stream_seed(42, "products") == stream_seed(42, "products")
    assert stream_seed(42, "products") != stream_seed(42, "brands")


def test_stream_seed_is_within_range() -> None:
    """The derived seed fits in the documented 64-bit width."""
    assert 0 <= stream_seed(42, "cities") < 2**64


def test_empty_stream_name_is_rejected() -> None:
    """An empty stream name is a programming error, not a valid stream."""
    with pytest.raises(ValueError, match="must not be empty"):
        stream_seed(42, "")


def test_make_rng_rejects_empty_stream() -> None:
    """The RNG factory propagates the empty-stream error."""
    with pytest.raises(ValueError, match="must not be empty"):
        make_rng(42, "")


def test_faker_is_seeded_per_stream() -> None:
    """Faker instances are reproducible and stream-specific."""
    first = make_faker(11, "suppliers").company()
    second = make_faker(11, "suppliers").company()
    other = make_faker(11, "brands").company()

    assert first == second
    assert first != other


def test_resolve_seed_passes_through_a_configured_seed() -> None:
    """A configured seed is used unchanged."""
    assert resolve_seed(99) == 99


def test_resolve_seed_generates_one_when_absent() -> None:
    """A null seed produces a concrete seed so the run stays reproducible."""
    generated = resolve_seed(None)

    assert isinstance(generated, int)
    assert generated >= 0
