"""Reading fields out of stored documents.

Five contract types read themselves back from documents and all of them need
the same four checks. Writing those checks five times would mean five chances
to forget that ``True`` is an integer in Python, or that a missing field and a
field holding ``None`` should not produce different messages.

Everything here raises :class:`~eds.platform.runtime.errors.RuntimeContractError`
with a message naming the field, because a caller reading a stored result needs
to know *which* of a dozen fields was wrong.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from eds.platform.runtime.errors import RuntimeContractError
from eds.platform.time.dates import parse_simulation_date

__all__ = [
    "require_date",
    "require_int",
    "require_list",
    "require_mapping",
    "require_str",
]


def require_str(document: dict[str, Any], field: str) -> str:
    """Read a required string field.

    Args:
        document: The stored document.
        field: Field name.

    Returns:
        The value.

    Raises:
        RuntimeContractError: If the field is absent or not a string.
    """
    value = document.get(field)
    if not isinstance(value, str):
        raise RuntimeContractError(f"field {field!r} must be a string, found {value!r}")
    return value


def require_int(document: dict[str, Any], field: str) -> int:
    """Read a required integer field.

    Args:
        document: The stored document.
        field: Field name.

    Returns:
        The value.

    Raises:
        RuntimeContractError: If the field is absent or not an integer.
            ``True`` is rejected: it is an integer only by accident of
            history, and a tick count of ``True`` is a corrupt document.
    """
    value = document.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeContractError(f"field {field!r} must be an integer, found {value!r}")
    return value


def require_date(document: dict[str, Any], field: str) -> date:
    """Read a required simulation date field.

    Args:
        document: The stored document.
        field: Field name.

    Returns:
        The date.

    Raises:
        RuntimeContractError: If the field is absent or not an ISO 8601 date.
    """
    try:
        return parse_simulation_date(document.get(field), field)
    except ValueError as exc:
        raise RuntimeContractError(str(exc)) from exc


def require_list(document: dict[str, Any], field: str) -> list[Any]:
    """Read a list field, defaulting to empty when absent.

    Args:
        document: The stored document.
        field: Field name.

    Returns:
        The list.

    Raises:
        RuntimeContractError: If the field is present and not a list.
    """
    value = document.get(field, [])
    if not isinstance(value, list):
        raise RuntimeContractError(f"field {field!r} must be a list, found {value!r}")
    return value


def require_mapping(document: dict[str, Any], field: str) -> dict[str, Any]:
    """Read an object field, defaulting to empty when absent.

    Args:
        document: The stored document.
        field: Field name.

    Returns:
        The mapping.

    Raises:
        RuntimeContractError: If the field is present and not an object.
    """
    value = document.get(field, {})
    if not isinstance(value, dict):
        raise RuntimeContractError(f"field {field!r} must be an object, found {value!r}")
    return value
