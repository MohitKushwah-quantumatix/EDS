"""Runtime contract failures.

There are only two, and that is the point. A contract is a record of facts, so
the only things that can go wrong with one are that a field is not a fact this
type can hold, or that a status moved somewhere it cannot move to. Everything
else that could go wrong belongs to whatever produced the contract.

Both are :class:`ValueError`. A caller building a result is passing arguments,
and rejecting an argument is what ``ValueError`` means; inheriting from it keeps
the platform's convention that a frozen record refuses a bad field with a
``ValueError`` and that a caller validating input need not know this package
exists.
"""

from __future__ import annotations

__all__ = ["InvalidStatusTransitionError", "RuntimeContractError"]


class RuntimeContractError(ValueError):
    """Raised when a value could not be a runtime fact.

    Covers a missing identifier, a negative row count, a stage recorded twice,
    a result whose status contradicts its failure, and a stored document that
    cannot be read back.
    """


class InvalidStatusTransitionError(RuntimeContractError):
    """Raised when a status was asked to move somewhere it cannot go.

    Separate from its parent because the remedy differs: a malformed field is
    a caller passing the wrong value, while an illegal transition is a caller
    whose model of the lifecycle is wrong.
    """
