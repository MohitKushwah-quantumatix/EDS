"""The business context for a Healthcare simulation day.

The platform hands the domain a date and a seed. Everything else the
domain needs is derived from those two inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from eds.core.random_streams import stream_seed

__all__ = ["BusinessContext"]


@dataclass(frozen=True, slots=True)
class BusinessContext:
    """The complete context for one simulated business day.

    Attributes:
        business_date: The date the day is trading on.
        seed: The resolved seed for the day's random streams.
    """

    business_date: date
    seed: int

    def __post_init__(self) -> None:
        """Reject a context that could not reproduce itself.

        Raises:
            ValueError: If the seed is negative.
        """
        if self.seed < 0:
            raise ValueError(f"a business seed must not be negative, got {self.seed}")

    def stream(self, name: str) -> int:
        """Return the seed for one named stream on this business date.

        Args:
            name: What the stream is for, such as ``"patients"``.

        Returns:
            A seed unique to the ``(enterprise, date, stream)`` triple, so a
            day's work is reproducible no matter which run generated it.

        Raises:
            ValueError: If ``name`` is empty.
        """
        return stream_seed(self.seed, f"{name}@{self.business_date.isoformat()}")
