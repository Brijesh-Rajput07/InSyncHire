# LOCATION: shared/auth-tokens/tests/test_token_service.py

"""
Tests for TokenService: proves the payload is genuinely encrypted (not
just base64/JWT-encoded), that expiry and revocation are enforced, and
that refresh rotation invalidates the old refresh token.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from auth_tokens import (
    TokenExpiredError,
    TokenFingerprintMismatchError,
    TokenInvalidError,
    TokenRevokedError,
    TokenService,
    generate_rsa_keypair_pem,
    session_fingerprint,
)
from cryptography.fernet import Fernet

from .conftest import build_fake_redis


def _service(**overrides) -> TokenService:
    private_pem, public_pem = generate_rsa_keypair_pem()
    defaults = dict(
        private_key_pem=private_pem,
        public_key_pem=public_pem,
        fernet_key=Fernet.generate_key().decode(),
        redis=build_fake_redis(),
        access_ttl_seconds=900,
        refresh_ttl_seconds=604800,
    )
    defaults.update(overrides)
    return TokenService(**defaults)


def test_session_fingerprint_is_deterministic_hash():
    fp1 = session_fingerprint("1.2.3.4", "Mozilla/5.0")
    fp2 = session_fingerprint("1.2.3.4", "Mozilla/5.0")
    fp3 = session_fingerprint("5.6.7.8", "Mozilla/5.0")
    assert fp1 == fp2
    assert fp1 != fp3


def test_issued_jwt_payload_is_actually_encrypted_not_plaintext():
    async def _run():
        service = _service()
        user_id = uuid.uuid4()
        tokens = await service.issue_token_pair(
            user_id=user_id, tenant_id=None, org_id=None, role=None, fingerprint="fp"
        )
        # Decode the JWT's claims WITHOUT verifying signature, to inspect
        # the raw "data" field the way an attacker who intercepted the
        # cookie (but not the Fernet key) would see it.
        unverified = jwt.decode(tokens.access_token, options={"verify_signature": False})
        assert str(user_id) not in unverified["data"]  # ciphertext, not plaintext
        assert "data" in unverified and "exp" in unverified and "jti" in unverified

    asyncio.run(_run())


def test_decode_and_verify_round_trip():
    async def _run():
        service = _service()
        user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
        tokens = await service.issue_token_pair(
            user_id=user_id, tenant_id=tenant_id, org_id=None, role="recruiter", fingerprint="fp-123"
        )
        payload = await service.decode_and_verify(tokens.access_token, expected_type="access")
        assert payload.user_id == user_id
        assert payload.tenant_id == tenant_id
        assert payload.role == "recruiter"
        assert payload.session_fingerprint == "fp-123"

    asyncio.run(_run())


def test_expected_type_mismatch_rejected():
    async def _run():
        service = _service()
        tokens = await service.issue_token_pair(
            user_id=uuid.uuid4(), tenant_id=None, org_id=None, role=None, fingerprint="fp"
        )
        with pytest.raises(TokenInvalidError):
            await service.decode_and_verify(tokens.access_token, expected_type="refresh")

    asyncio.run(_run())


def test_expired_token_rejected():
    async def _run():
        service = _service(access_ttl_seconds=-1)  # already expired the instant it's issued
        tokens = await service.issue_token_pair(
            user_id=uuid.uuid4(), tenant_id=None, org_id=None, role=None, fingerprint="fp"
        )
        with pytest.raises(TokenExpiredError):
            await service.decode_and_verify(tokens.access_token, expected_type="access")

    asyncio.run(_run())


def test_revoke_invalidates_token():
    async def _run():
        service = _service()
        tokens = await service.issue_token_pair(
            user_id=uuid.uuid4(), tenant_id=None, org_id=None, role=None, fingerprint="fp"
        )
        payload = await service.decode_and_verify(tokens.access_token, expected_type="access")
        await service.revoke(payload.jti, ttl_seconds=900)

        with pytest.raises(TokenRevokedError):
            await service.decode_and_verify(tokens.access_token, expected_type="access")

    asyncio.run(_run())


def test_revoke_all_for_user_blocks_old_tokens_but_not_future_logins():
    async def _run():
        service = _service()
        user_id = uuid.uuid4()
        old_tokens = await service.issue_token_pair(
            user_id=user_id, tenant_id=None, org_id=None, role=None, fingerprint="fp"
        )

        await service.revoke_all_for_user(user_id)

        with pytest.raises(TokenRevokedError):
            await service.decode_and_verify(old_tokens.access_token, expected_type="access")

        # A fresh login AFTER the revocation must still work
        new_tokens = await service.issue_token_pair(
            user_id=user_id, tenant_id=None, org_id=None, role=None, fingerprint="fp"
        )
        payload = await service.decode_and_verify(new_tokens.access_token, expected_type="access")
        assert payload.user_id == user_id

    asyncio.run(_run())


def test_refresh_rotates_and_invalidates_old_refresh_token():
    async def _run():
        service = _service()
        user_id = uuid.uuid4()
        tokens = await service.issue_token_pair(
            user_id=user_id, tenant_id=None, org_id=None, role="recruiter", fingerprint="fp"
        )

        new_tokens = await service.refresh(tokens.refresh_token, current_fingerprint="fp")
        assert new_tokens.access_token != tokens.access_token
        assert new_tokens.refresh_token != tokens.refresh_token

        # Old refresh token must now be rejected (rotation-on-use)
        with pytest.raises(TokenRevokedError):
            await service.refresh(tokens.refresh_token, current_fingerprint="fp")

        # New tokens work and preserve identity/role
        payload = await service.decode_and_verify(new_tokens.access_token, expected_type="access")
        assert payload.user_id == user_id
        assert payload.role == "recruiter"

    asyncio.run(_run())


def test_tampered_signature_rejected():
    async def _run():
        service = _service()
        tokens = await service.issue_token_pair(
            user_id=uuid.uuid4(), tenant_id=None, org_id=None, role=None, fingerprint="fp"
        )
        tampered = tokens.access_token[:-2] + ("XY" if tokens.access_token[-2:] != "XY" else "ZZ")
        with pytest.raises(TokenInvalidError):
            await service.decode_and_verify(tampered, expected_type="access")

    asyncio.run(_run())


# --- FIX-M2: session_fingerprint re-validation ---

def test_decode_and_verify_without_fingerprint_arg_skips_check():
    """Backward-compatible default: callers that don't pass
    current_fingerprint get signature-only verification (used internally,
    e.g. by refresh() re-deriving trust from the payload itself) -- but
    see test_matching_fingerprint_succeeds / test_mismatched_fingerprint_
    below for why every REAL request-handling call site must pass it."""

    async def _run():
        service = _service()
        tokens = await service.issue_token_pair(
            user_id=uuid.uuid4(), tenant_id=None, org_id=None, role=None, fingerprint="fp-original"
        )
        # No current_fingerprint passed -- succeeds even though a real
        # request's fingerprint might differ, by design (opt-in check).
        payload = await service.decode_and_verify(tokens.access_token, expected_type="access")
        assert payload.session_fingerprint == "fp-original"

    asyncio.run(_run())


def test_matching_fingerprint_succeeds():
    async def _run():
        service = _service()
        tokens = await service.issue_token_pair(
            user_id=uuid.uuid4(), tenant_id=None, org_id=None, role=None, fingerprint="fp-original"
        )
        payload = await service.decode_and_verify(
            tokens.access_token, expected_type="access", current_fingerprint="fp-original"
        )
        assert payload.session_fingerprint == "fp-original"

    asyncio.run(_run())


def test_mismatched_fingerprint_rejected_and_token_revoked():
    """The core FIX-M2 behavior: a token replayed from a different
    device/IP (different fingerprint) is rejected AND immediately
    revoked -- it can't be retried even with the correct fingerprint
    afterward, since the token itself is now dead."""

    async def _run():
        service = _service()
        tokens = await service.issue_token_pair(
            user_id=uuid.uuid4(), tenant_id=None, org_id=None, role=None, fingerprint="fp-original-device"
        )

        with pytest.raises(TokenFingerprintMismatchError):
            await service.decode_and_verify(
                tokens.access_token, expected_type="access", current_fingerprint="fp-attacker-device"
            )

        # Even retrying with the CORRECT fingerprint now fails -- the
        # token was revoked the moment the mismatch was detected.
        with pytest.raises(TokenRevokedError):
            await service.decode_and_verify(
                tokens.access_token, expected_type="access", current_fingerprint="fp-original-device"
            )

    asyncio.run(_run())


def test_refresh_requires_matching_fingerprint():
    async def _run():
        service = _service()
        tokens = await service.issue_token_pair(
            user_id=uuid.uuid4(), tenant_id=None, org_id=None, role=None, fingerprint="fp-original"
        )

        with pytest.raises(TokenFingerprintMismatchError):
            await service.refresh(tokens.refresh_token, current_fingerprint="fp-different")

    asyncio.run(_run())
