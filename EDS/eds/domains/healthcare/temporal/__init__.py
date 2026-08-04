"""Healthcare over simulated time.

The rest of the domain answers "what does this enterprise look like". This
package answers "what does a day do to it".

:mod:`~eds.domains.healthcare.temporal.context` - the business date, and nothing else.
:mod:`~eds.domains.healthcare.temporal.temporality` - what each dataset does when a day passes.
:mod:`~eds.domains.healthcare.temporal.identity` - how a day's identifiers continue.
:mod:`~eds.domains.healthcare.temporal.merge` - how a day joins history.
:mod:`~eds.domains.healthcare.temporal.evolution` - what actually happens on a day.
:mod:`~eds.domains.healthcare.temporal.day` - decides whether a stage is founding or continuing.
:mod:`~eds.domains.healthcare.temporal.rules` - temporal invariant checks.
"""

from eds.domains.healthcare.temporal.context import BusinessContext
from eds.domains.healthcare.temporal.day import (
    DayOfBusiness,
    advance_day,
)
from eds.domains.healthcare.temporal.rules import validate_temporal_history
from eds.domains.healthcare.temporal.temporality import (
    Temporality,
    temporality_of,
)

__all__ = [
    "BusinessContext",
    "DayOfBusiness",
    "Temporality",
    "advance_day",
    "temporality_of",
    "validate_temporal_history",
]
