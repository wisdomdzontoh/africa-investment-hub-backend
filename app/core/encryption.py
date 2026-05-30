"""Application-layer field encryption (AES-256-GCM).

Sensitive fields — company registration numbers and financial figures
(PRD §14) — are encrypted before they touch Postgres and decrypted on read,
transparently, via a SQLAlchemy ``TypeDecorator``.

Storage format (urlsafe-base64 of):  nonce(12) || ciphertext || tag(16)
A 1-byte version prefix allows future key rotation / algorithm changes.
"""

from __future__ import annotations

import base64
import os
from decimal import Decimal
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.core.config import settings

_VERSION = b"\x01"
_NONCE_BYTES = 12


class EncryptionKeyError(RuntimeError):
    """Raised when the configured encryption key is missing or malformed."""


def _load_key() -> bytes:
    raw = settings.FIELD_ENCRYPTION_KEY
    if not raw:
        raise EncryptionKeyError(
            "FIELD_ENCRYPTION_KEY is not set. Generate one with: "
            "python -c \"import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())\""
        )
    try:
        key = base64.urlsafe_b64decode(raw)
    except Exception as exc:  # noqa: BLE001
        raise EncryptionKeyError("FIELD_ENCRYPTION_KEY is not valid base64.") from exc
    if len(key) != 32:
        raise EncryptionKeyError("FIELD_ENCRYPTION_KEY must decode to 32 bytes (AES-256).")
    return key


def encrypt_str(plaintext: str) -> str:
    aesgcm = AESGCM(_load_key())
    nonce = os.urandom(_NONCE_BYTES)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(_VERSION + nonce + ct).decode("ascii")


def decrypt_str(token: str) -> str:
    blob = base64.urlsafe_b64decode(token)
    version, nonce, ct = blob[:1], blob[1 : 1 + _NONCE_BYTES], blob[1 + _NONCE_BYTES :]
    if version != _VERSION:
        raise EncryptionKeyError(f"Unsupported encryption version: {version!r}")
    aesgcm = AESGCM(_load_key())
    return aesgcm.decrypt(nonce, ct, None).decode("utf-8")


class EncryptedString(TypeDecorator[str]):
    """Transparently AES-256-GCM-encrypted string column."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return encrypt_str(value)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return decrypt_str(value)


class EncryptedDecimal(TypeDecorator[Decimal]):
    """Decimal stored encrypted as a string. For sensitive financial figures."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Decimal | int | float | None, dialect: Any) -> str | None:
        if value is None:
            return None
        return encrypt_str(str(value))

    def process_result_value(self, value: str | None, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return Decimal(decrypt_str(value))
