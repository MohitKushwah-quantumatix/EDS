"""The date vocabulary of a simulation.

**A simulation date is a :class:`datetime.date`.** :data:`SimulationDate` is an
alias, not a wrapper.

That is a decision rather than an omission. A wrapper type would buy nothing -
:class:`datetime.date` is already immutable, ordered, hashable and serialisable
- and it would cost a conversion at every boundary: P003 already stores
``current_date`` as a ``date``, Retail's generators already work in ``date``,
and Polars already has a date type. Wrapping would introduce a translation
layer between three things that already agree.

What the alias does buy is a name. ``SimulationDate`` in a signature says
*simulated* time rather than wall-clock time, which is the distinction that
actually matters here, and it leaves room to become a real type later if one
is ever needed.

Parsing is stricter than :meth:`datetime.date.fromisoformat`, which since
Python 3.11 also accepts ``"20240101"``, ``"2024-W01-1"`` and full timestamps.
One spelling, ISO 8601 ``YYYY-MM-DD``, is what a stored document and a
configuration file should both contain.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Final

from eds.platform.time.errors import InvalidDateError

__all__ = [
    "MAX_SIMULATION_DATE",
    "MIN_SIMULATION_DATE",
    "SimulationDate",
    "format_simulation_date",
    "parse_simulation_date",
]

#: A day in simulated time. An alias for :class:`datetime.date`, deliberately.
type SimulationDate = date

#: The earliest representable simulation date.
MIN_SIMULATION_DATE: Final[date] = date.min

#: The latest representable simulation date. Advancement past it overflows.
MAX_SIMULATION_DATE: Final[date] = date.max

#: The one accepted spelling: four-digit year, two-digit month, two-digit day.
_ISO_DATE: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_simulation_date(text: object, field: str = "date") -> date:
    """Read a simulation date from ISO 8601 text.

    Accepts :class:`object` rather than :class:`str` because its callers read
    from stored documents, where the value could be anything. Rejecting a
    non-string here produces one descriptive error instead of making every
    caller type-check first.

    Args:
        text: The text to read, in ``YYYY-MM-DD`` form.
        field: What is being read, used in the error message so a caller knows
            which of several dates was rejected.

    Returns:
        The date.

    Raises:
        InvalidDateError: If the text is not a string, is not in ``YYYY-MM-DD``
            form, or names a day that does not exist.
    """
    if not isinstance(text, str):
        raise InvalidDateError(f"{field} must be a string in YYYY-MM-DD form, found {text!r}")
    candidate = text.strip()
    if not _ISO_DATE.match(candidate):
        raise InvalidDateError(f"{field} {text!r} is not an ISO 8601 date in YYYY-MM-DD form")
    try:
        return date.fromisoformat(candidate)
    except ValueError as exc:
        raise InvalidDateError(f"{field} {text!r} is not a real date: {exc}") from exc


def format_simulation_date(value: date) -> str:
    """Render a simulation date for storage.

    Args:
        value: The date.

    Returns:
        The date in ``YYYY-MM-DD`` form, which
        :func:`parse_simulation_date` reads back unchanged.
    """
    return value.isoformat()
