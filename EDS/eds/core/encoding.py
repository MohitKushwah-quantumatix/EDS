"""Value encoding utilities for sensitive PII/PHI fields.

Provides deterministic encoding (hash → URL-safe base64) so that PII such as
email addresses, phone numbers, and license numbers are stored as compact
opaque tokens that reveal no information about the original value.
"""

from __future__ import annotations

import base64
import hashlib

__all__ = ["encode_hash"]


def encode_hash(value: str) -> str:
    """Encode a string into a fixed-length URL-safe base64 token.

    Uses SHA-256, then takes the first 8 bytes (11 base64 characters after
    padding is stripped).  Deterministic: identical inputs always produce
    identical outputs.

    Args:
        value: The plaintext string to encode.

    Returns:
        An 11-character URL-safe base64 string.
    """
    hash_bytes = hashlib.sha256(value.encode("utf-8")).digest()[:8]
    return base64.urlsafe_b64encode(hash_bytes).decode("ascii").rstrip("=")
