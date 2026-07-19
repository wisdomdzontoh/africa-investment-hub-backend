"""Unit tests for Clerk JWT verification (the real signature path).

Integration tests override auth, so this is where ``verify_token`` and the
JWKS handling actually run. We mint a local RSA keypair, publish it as a JWKS,
and sign tokens with it.
"""

from __future__ import annotations

import datetime
import json

import jwt
import pytest
from app.core import config, security
from app.core.exceptions import UnauthorizedError
from app.models.enums import UserRole
from cryptography.hazmat.primitives.asymmetric import rsa

_KID = "test-kid-1"
_ISSUER = "https://clerk.test.example"


@pytest.fixture
def keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _jwks(public_key) -> dict:
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(public_key, as_dict=True)
    if isinstance(jwk, str):
        jwk = json.loads(jwk)
    jwk.update({"kid": _KID, "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


def _token(private_key, claims: dict) -> str:
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": _KID})


@pytest.fixture(autouse=True)
def _patch_jwks(keypair, monkeypatch):
    _, public_key = keypair

    async def _fake_fetch() -> dict:
        return _jwks(public_key)

    monkeypatch.setattr(security, "_fetch_jwks", _fake_fetch)
    # Pin issuer/audience so a host .env (e.g. the dev container's real Clerk
    # issuer) can never leak into these tests and change their outcome.
    monkeypatch.setattr(config.settings, "CLERK_ISSUER", _ISSUER)
    monkeypatch.setattr(config.settings, "CLERK_AUDIENCE", None)


async def test_valid_token(keypair) -> None:
    private_key, _ = keypair
    token = _token(
        private_key,
        {"sub": "clerk_abc", "email": "a@b.com", "role": "investor", "iss": _ISSUER},
    )
    claims = await security.verify_token(token)
    assert claims.clerk_id == "clerk_abc"
    assert claims.email == "a@b.com"
    assert claims.role == UserRole.investor


async def test_wrong_issuer_rejected(keypair) -> None:
    private_key, _ = keypair
    token = _token(
        private_key, {"sub": "clerk_abc", "iss": "https://attacker.example"}
    )
    with pytest.raises(UnauthorizedError):
        await security.verify_token(token)


async def test_expired_token(keypair) -> None:
    private_key, _ = keypair
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=2)
    token = _token(private_key, {"sub": "x", "exp": past, "iss": _ISSUER})
    with pytest.raises(UnauthorizedError):
        await security.verify_token(token)


async def test_unknown_kid(keypair) -> None:
    private_key, _ = keypair
    token = jwt.encode({"sub": "x"}, private_key, algorithm="RS256", headers={"kid": "other"})
    with pytest.raises(UnauthorizedError):
        await security.verify_token(token)


async def test_malformed_token() -> None:
    with pytest.raises(UnauthorizedError):
        await security.verify_token("not-a-jwt")


async def test_token_missing_subject(keypair) -> None:
    private_key, _ = keypair
    token = _token(private_key, {"email": "a@b.com", "iss": _ISSUER})
    with pytest.raises(UnauthorizedError):
        await security.verify_token(token)
