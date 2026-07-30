"""What Retail knows about time.

One value object, and it is deliberately small. The platform owns simulated
time; Retail owns what a business does with it. The whole of that hand-over is
:class:`BusinessContext`: a date and a seed.

Notice what is *not* here. There is no clock, no tick, no calendar, no run, no
plan and no project. Retail cannot advance time, cannot ask what time it is,
and cannot tell how many days a tick was worth. It is told a business date and
it trades on that date. That is the entire contract, and keeping it this thin
is what lets Retail stay executable without the platform (PADR-002).

**The seed is derived per day, not per tick.** Two runs that reach 3 March by
different routes - one thirty-day run, three ten-day runs, a run that failed
and was continued - must produce the same business on 3 March. A tick *index*
would not survive that; a date does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from eds.core.random_streams import stream_seed

__all__ = ["BusinessContext"]


@dataclass(frozen=True, slots=True)
class BusinessContext:
    """The business date one unit of work is performed on.

    Attributes:
        business_date: The date the work belongs to. Everything generated for
            this unit of work is dated on or after it.
        seed: The enterprise's seed, from which every day's own seed derives.
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
            name: What the stream is for, such as ``"customers"``.

        Returns:
            A seed unique to the ``(enterprise, date, stream)`` triple, so a
            day's work is reproducible no matter which run generated it.

        Raises:
            ValueError: If ``name`` is empty.
        """
        return stream_seed(self.seed, f"{name}@{self.business_date.isoformat()}")
