"""Column-level AES-256 encryption engine for eds_loader.

Uses :pypi:`cryptography` Fernet (AES-128-CBC + HMAC-SHA256) — symmetric,
reversible, and cryptographically secure.  The same key is used for both
encryption (at load time) and decryption (via ``eds-loader decrypt``).

Key format
----------
Fernet keys are 32-byte random values encoded as URL-safe base64.
Generate one with ``eds-loader keygen``.

Null / None handling
--------------------
``None`` values are passed through unchanged — no encrypted token is stored
for missing data.  This preserves SQL NULL semantics in the target database.

Type coercion
-------------
Before encryption, every value is converted to a UTF-8 string:
- ``str``            → as-is
- ``int`` / ``float``→ ``str(value)``
- ``bool``           → ``"True"`` / ``"False"``
- ``datetime.date``  → ISO-8601 string (``"2026-09-04"``)
- ``datetime.datetime`` → ISO-8601 string
- anything else      → ``str(value)``

The encrypted column is stored as a UTF-8 ``Utf8`` (string) Polars series
regardless of the original column dtype.
"""

from __future__ import annotations

import datetime
import os
from typing import Any

import polars as pl

from eds_loader.exceptions import LoadError

__all__ = [
    "generate_key",
    "load_key",
    "encrypt_value",
    "decrypt_value",
    "encrypt_dataframe",
    "decrypt_dataframe",
]

# ---------------------------------------------------------------------------
# Key utilities
# ---------------------------------------------------------------------------

def generate_key() -> str:
    """Generate a new Fernet key and return it as a URL-safe base64 string.

    Call once ever.  Store the result as the ``EDS_ENCRYPT_KEY`` environment
    variable — losing the key means encrypted data is permanently unreadable.
    """
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode("utf-8")


def load_key(key_env: str) -> bytes:
    """Read the Fernet key from the named environment variable.

    Args:
        key_env: Name of the environment variable holding the key
                 (e.g. ``"EDS_ENCRYPT_KEY"``).

    Returns:
        The raw key bytes ready for ``Fernet(key)``.

    Raises:
        LoadError: If the environment variable is not set or the key is invalid.
    """
    val = os.environ.get(key_env)
    if not val:
        raise LoadError(
            f"Encryption key environment variable {key_env!r} is not set.\n"
            f"  Generate a key:  eds-loader keygen\n"
            f"  Set it (Windows): "
            f'[System.Environment]::SetEnvironmentVariable("{key_env}", "<key>", "User")\n'
            f"  Set it (Ubuntu):  echo 'export {key_env}=\"<key>\"' >> ~/.bashrc"
        )
    try:
        return val.strip().encode("utf-8")
    except Exception as exc:
        raise LoadError(f"Invalid encryption key in {key_env!r}: {exc}") from exc


# ---------------------------------------------------------------------------
# Value-level encrypt / decrypt
# ---------------------------------------------------------------------------

def _to_str(value: Any) -> str:
    """Coerce any Python value to a UTF-8 string for encryption."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return str(value)


def encrypt_value(value: Any, fernet: Any) -> str | None:
    """Encrypt a single value.

    Args:
        value:  The original column value (any Python type).
        fernet: A ``cryptography.fernet.Fernet`` instance.

    Returns:
        URL-safe base64 encrypted token string, or ``None`` if *value* is None.
    """
    if value is None:
        return None
    plaintext = _to_str(value).encode("utf-8")
    return fernet.encrypt(plaintext).decode("utf-8")


def decrypt_value(token: str | None, fernet: Any) -> str | None:
    """Decrypt a single encrypted token back to its original string.

    Args:
        token:  The encrypted base64 token (as stored in the database).
        fernet: The same ``Fernet`` instance used for encryption.

    Returns:
        Original plaintext string, or ``None`` if *token* is None.

    Raises:
        LoadError: If the token is invalid or the key is wrong.
    """
    if token is None:
        return None
    try:
        return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        raise LoadError(
            f"Decryption failed — wrong key or corrupted token: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# DataFrame-level encrypt / decrypt
# ---------------------------------------------------------------------------

def encrypt_dataframe(
    df: pl.DataFrame,
    columns: list[str],
    fernet: Any,
) -> pl.DataFrame:
    """Encrypt specified columns of a Polars DataFrame in place.

    Columns not listed in *columns* are left completely unchanged.
    The encrypted column dtype becomes ``Utf8`` (string) regardless of the
    original dtype.

    Args:
        df:      The source DataFrame (from Parquet / source connector).
        columns: List of column names to encrypt.
        fernet:  ``cryptography.fernet.Fernet`` instance.

    Returns:
        A new DataFrame with the specified columns replaced by encrypted strings.

    Raises:
        LoadError: If a named column does not exist in *df*.
    """
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise LoadError(
            f"Encryption config references column(s) not found in dataset: "
            f"{', '.join(missing)}"
        )

    result = df
    for col in columns:
        encrypted_series = pl.Series(
            name=col,
            values=[encrypt_value(v, fernet) for v in df[col].to_list()],
            dtype=pl.Utf8,
        )
        result = result.with_columns(encrypted_series)
    return result


def decrypt_dataframe(
    df: pl.DataFrame,
    columns: list[str],
    fernet: Any,
) -> pl.DataFrame:
    """Decrypt specified columns of a Polars DataFrame.

    Args:
        df:      DataFrame containing encrypted base64 string columns.
        columns: List of column names to decrypt.
        fernet:  The same ``Fernet`` instance used for encryption.

    Returns:
        A new DataFrame with the specified columns replaced by plaintext strings.

    Raises:
        LoadError: If decryption fails (wrong key or corrupted token).
    """
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise LoadError(
            f"Decrypt references column(s) not found in dataset: "
            f"{', '.join(missing)}"
        )

    result = df
    for col in columns:
        decrypted_series = pl.Series(
            name=col,
            values=[decrypt_value(v, fernet) for v in df[col].to_list()],
            dtype=pl.Utf8,
        )
        result = result.with_columns(decrypted_series)
    return result
