"""Document persistence.

**The store's currency is a document, not bytes and not a file.** A document is
a plain mapping of primitives - the same thing a JSON object, a YAML mapping, a
database row and a cloud object body can all carry.

That is the level the abstraction has to sit at. A byte-oriented store
(``read(key) -> bytes``) would push serialisation onto every caller, so every
caller would have to agree on a format and the format would leak everywhere. A
typed store (``read_manifest() -> ProjectManifest``) would make the store know
about project types, so a second document kind would mean a new method.

With documents, JSON is an implementation detail of one store. A database store
would map a document to columns; an object store would map it to a body. None
of them changes this interface, and none of them changes a caller.

Keys are logical names - ``"manifest"``, ``"state"`` - not paths. A file store
turns them into filenames; a database store would turn them into rows.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

from eds.platform.project.errors import CorruptDocumentError, StateStoreError

__all__ = ["Document", "FileStateStore", "StateStore"]

#: A plain mapping of primitives. Anything a JSON object, a YAML mapping, a
#: database row or an object body can carry, and nothing else - no callables,
#: no frames, no open handles.
type Document = Mapping[str, Any]

#: JSON encoding settings chosen for reproducibility rather than compactness:
#: sorted keys and a fixed indent mean the same document always produces the
#: same bytes, so a project directory can be diffed and checksummed.
_JSON_INDENT: Final[int] = 2


@runtime_checkable
class StateStore(Protocol):
    """Persists and retrieves documents by logical key.

    Implementations must be deterministic: writing the same document twice
    produces the same stored result, which is what allows a project directory
    to be compared between runs.
    """

    @property
    def name(self) -> str:
        """Return the store's kind, such as ``"file"``."""
        ...

    def exists(self, key: str) -> bool:
        """Report whether a document is stored under a key.

        Args:
            key: Logical document name.

        Returns:
            Whether the document exists.
        """
        ...

    def read(self, key: str) -> dict[str, Any]:
        """Read one document.

        Args:
            key: Logical document name.

        Returns:
            The stored document.

        Raises:
            StateStoreError: If the document is absent or unreadable.
            CorruptDocumentError: If it exists but cannot be understood.
        """
        ...

    def write(self, key: str, document: Document) -> None:
        """Write one document, replacing any previous value.

        Args:
            key: Logical document name.
            document: The document to store.

        Raises:
            StateStoreError: If the document cannot be written.
        """
        ...


class FileStateStore:
    """Stores documents as JSON files in a directory.

    Satisfies :class:`StateStore`. JSON is this store's private encoding, not
    part of the interface: replacing it changes this class and nothing else.
    """

    def __init__(self, directory: Path) -> None:
        """Point the store at a directory.

        Args:
            directory: Where documents are read from and written to. Created
                on first write if absent.
        """
        self._directory = directory

    @property
    def name(self) -> str:
        """Return the store's kind."""
        return "file"

    @property
    def directory(self) -> Path:
        """Return the directory this store is bound to."""
        return self._directory

    def path_for(self, key: str) -> Path:
        """Return the file a key maps to.

        Exposed because a caller diagnosing a project needs to be able to say
        *which file* is wrong. It is specific to this store and no part of the
        :class:`StateStore` protocol.

        Args:
            key: Logical document name.

        Returns:
            The file path.
        """
        return self._directory / f"{key}.json"

    def exists(self, key: str) -> bool:
        """Report whether a document is stored under a key.

        Args:
            key: Logical document name.

        Returns:
            Whether the file exists.
        """
        return self.path_for(key).is_file()

    def read(self, key: str) -> dict[str, Any]:
        """Read one document from its JSON file.

        Args:
            key: Logical document name.

        Returns:
            The stored document.

        Raises:
            StateStoreError: If the file is absent or unreadable.
            CorruptDocumentError: If it is not valid JSON, or is valid JSON
                that is not an object.
        """
        path = self.path_for(key)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise StateStoreError(f"No {key!r} document at {path}") from exc
        except OSError as exc:  # pragma: no cover - platform dependent
            raise StateStoreError(f"Could not read {key!r} document at {path}: {exc}") from exc

        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CorruptDocumentError(
                f"{key!r} document at {path} is not valid JSON: {exc}"
            ) from exc

        if not isinstance(document, dict):
            raise CorruptDocumentError(
                f"{key!r} document at {path} must be an object, found {type(document).__name__}"
            )
        return document

    def write(self, key: str, document: Document) -> None:
        """Write one document as JSON, replacing any previous value.

        Args:
            key: Logical document name.
            document: The document to store.

        Raises:
            StateStoreError: If the document cannot be serialised or written.
        """
        path = self.path_for(key)
        try:
            text = json.dumps(dict(document), indent=_JSON_INDENT, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise StateStoreError(f"{key!r} document cannot be serialised: {exc}") from exc

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
        except OSError as exc:  # pragma: no cover - platform dependent
            raise StateStoreError(f"Could not write {key!r} document to {path}: {exc}") from exc
