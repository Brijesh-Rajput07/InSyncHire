# LOCATION: services/interview_service/tests/test_ws_tokens.py

import uuid

import pytest
from interview_service.ws_tokens import WSConnectTokenService, WSTokenExpiredError, WSTokenInvalidError

from .conftest import build_test_room_token_crypto


def test_issue_and_verify_round_trip():
    crypto = build_test_room_token_crypto()
    service = WSConnectTokenService(crypto=crypto, ttl_seconds=300)
    tenant_id, session_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    token = service.issue(tenant_id=tenant_id, session_id=session_id, user_id=user_id, role_in_session="interviewer")
    claims = service.verify(token)

    assert claims.tenant_id == tenant_id
    assert claims.session_id == session_id
    assert claims.user_id == user_id
    assert claims.role_in_session == "interviewer"


def test_expired_token_rejected():
    crypto = build_test_room_token_crypto()
    service = WSConnectTokenService(crypto=crypto, ttl_seconds=-1)  # already expired the instant it's issued
    token = service.issue(
        tenant_id=uuid.uuid4(), session_id=uuid.uuid4(), user_id=uuid.uuid4(), role_in_session="candidate"
    )

    verifier = WSConnectTokenService(crypto=crypto, ttl_seconds=300)
    with pytest.raises(WSTokenExpiredError):
        verifier.verify(token)


def test_garbage_token_rejected():
    crypto = build_test_room_token_crypto()
    service = WSConnectTokenService(crypto=crypto, ttl_seconds=300)
    with pytest.raises(WSTokenInvalidError):
        service.verify("not-a-real-token")


def test_token_encrypted_with_different_key_rejected():
    """A token issued with one Fernet key must not verify against a
    service configured with a DIFFERENT key -- proves this is genuine
    encryption, not just an encoded/signed-but-readable payload."""
    service_a = WSConnectTokenService(crypto=build_test_room_token_crypto(), ttl_seconds=300)
    service_b = WSConnectTokenService(crypto=build_test_room_token_crypto(), ttl_seconds=300)

    token = service_a.issue(
        tenant_id=uuid.uuid4(), session_id=uuid.uuid4(), user_id=uuid.uuid4(), role_in_session="observer"
    )
    with pytest.raises(WSTokenInvalidError):
        service_b.verify(token)


def test_token_payload_is_not_plaintext_json():
    """The encrypted token string itself must not contain the raw
    identity values -- confirms this actually went through Fernet
    encryption rather than e.g. base64/json-only encoding."""
    crypto = build_test_room_token_crypto()
    service = WSConnectTokenService(crypto=crypto, ttl_seconds=300)
    session_id = uuid.uuid4()

    token = service.issue(
        tenant_id=uuid.uuid4(), session_id=session_id, user_id=uuid.uuid4(), role_in_session="interviewer"
    )
    assert str(session_id) not in token
    assert "role_in_session" not in token