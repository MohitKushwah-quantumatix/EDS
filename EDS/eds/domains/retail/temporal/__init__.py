"""Retail over simulated time.

The rest of the domain answers "what does this enterprise look like". This
package answers "what does a day do to it", which turns out to need five
things and no more:

* :mod:`~eds.domains.retail.temporal.context` - the business date, and nothing
  else. The whole of what the platform hands the domain.
* :mod:`~eds.domains.retail.temporal.temporality` - what each of the
  thirty-nine datasets does when a day passes.
* :mod:`~eds.domains.retail.temporal.identity` - how a day's identifiers
  continue rather than restart.
* :mod:`~eds.domains.retail.temporal.merge` - how a day joins history without
  disturbing it.
* :mod:`~eds.domains.retail.temporal.evolution` - what actually happens on a
  day, and :mod:`~eds.domains.retail.temporal.day`, which decides whether a
  stage is founding one or continuing one.

:mod:`~eds.domains.retail.temporal.rules` states the invariants that only
exist because there is more than one day.

Nothing here knows about a clock, a tick, a scheduler, a run, a plan or a
project. Retail is told a date and trades on it.
"""

from eds.domains.retail.temporal.context import BusinessContext
from eds.domains.retail.temporal.day import (
    HISTORY_READ,
    RETAIL_STAGE_NAMES,
    STAGE_DATASETS,
    DayOfBusiness,
    advance_day,
)
from eds.domains.retail.temporal.rules import validate_temporal_history
from eds.domains.retail.temporal.temporality import DATASET_TEMPORALITY, Temporality, temporality_of

__all__ = [
    "DATASET_TEMPORALITY",
    "HISTORY_READ",
    "RETAIL_STAGE_NAMES",
    "STAGE_DATASETS",
    "BusinessContext",
    "DayOfBusiness",
    "Temporality",
    "advance_day",
    "temporality_of",
    "validate_temporal_history",
]
