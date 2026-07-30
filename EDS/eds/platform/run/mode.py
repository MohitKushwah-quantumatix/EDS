"""What a run is for.

A run mode answers one question: **which stages should run?** Three answers
cover it - all of them, some named ones, or the ones not yet done.

**Dry run is deliberately not a mode.** The brief listed it beside the other
three, and it does not belong there: "which stages" and "does anything get
written" are independent questions, and folding them into one enum makes
combinations inexpressible. A dry run of a resume is an obviously useful thing
to ask for - *what would resuming actually do?* - and with four modes there is
no way to say it. So :class:`RunMode` answers which stages, and
``RunConfiguration.dry_run`` answers whether output is produced. Four concepts
are still represented; twelve combinations are expressible rather than four.
The reasoning is recorded in PADR-011.

A mode is a **declaration of intent**, not behaviour. Nothing here skips a
stage or suppresses a write; a scheduler reads the mode and decides what to do
about it. The platform's job is to make the intent unambiguous and to refuse
the combinations that contradict themselves.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["RunMode"]


class RunMode(StrEnum):
    """Which stages of a plan a run is asking for.

    Attributes:
        FULL: Every stage in the plan. The default.
        TARGETED: Named stages and whatever they depend on. Requires targets,
            and is the only mode that accepts them.
        RESUME: The stages the project's state does not already record as
            completed. Continues an interrupted run.
    """

    FULL = "full"
    TARGETED = "targeted"
    RESUME = "resume"

    @property
    def accepts_targets(self) -> bool:
        """Report whether this mode is the one that takes named stages.

        Targets and mode are not independent: naming stages *is* what makes a
        run targeted, so a full run with targets is a contradiction rather
        than a refinement.
        """
        return self is RunMode.TARGETED
