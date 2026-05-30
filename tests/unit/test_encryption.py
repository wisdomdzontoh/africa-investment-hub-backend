"""Unit tests for AES-256-GCM field encryption."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.encryption import (
    EncryptedString,
    EncryptionKeyError,
    decrypt_str,
    encrypt_str,
)


def test_roundtrip_str() -> None:
    plaintext = "RC-123456-GH"
    token = encrypt_str(plaintext)
    assert token != plaintext
    assert decrypt_str(token) == plaintext


def test_ciphertext_is_nondeterministic() -> None:
    # Random nonce per encryption → two ciphertexts differ.
    assert encrypt_str("same") != encrypt_str("same")


def test_tamper_detection() -> None:
    token = encrypt_str("secret")
    # Flip a character in the middle of the base64 payload.
    tampered = token[:-4] + ("A" if token[-4] != "A" else "B") + token[-3:]
    with pytest.raises(Exception):  # noqa: B017 - any crypto failure is acceptable
        decrypt_str(tampered)


def test_type_decorator_bind_and_result() -> None:
    col = EncryptedString()
    stored = col.process_bind_param("hello", None)
    assert stored is not None and stored != "hello"
    assert col.process_result_value(stored, None) == "hello"
    assert col.process_bind_param(None, None) is None
    assert col.process_result_value(None, None) is None


def test_missing_key_raises(monkeypatch) -> None:
    from app.core import encryption

    monkeypatch.setattr(encryption.settings, "FIELD_ENCRYPTION_KEY", "")
    with pytest.raises(EncryptionKeyError):
        encrypt_str("x")
