# LOCATION: services/auth_service/tests/test_password_service.py

from auth_service.services.password_service import hash_password, verify_password


def test_hash_is_not_plaintext():
    h = hash_password("correct-horse-battery-staple")
    assert h != "correct-horse-battery-staple"
    assert h.startswith("$2b$") or h.startswith("$2a$")  # bcrypt prefix


def test_verify_correct_password():
    h = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", h) is True


def test_verify_wrong_password():
    h = hash_password("correct-horse-battery-staple")
    assert verify_password("wrong-password", h) is False


def test_verify_handles_malformed_hash_gracefully():
    assert verify_password("anything", "not-a-real-bcrypt-hash") is False


def test_same_password_produces_different_hashes_due_to_salt():
    h1 = hash_password("same-password-123")
    h2 = hash_password("same-password-123")
    assert h1 != h2
    assert verify_password("same-password-123", h1)
    assert verify_password("same-password-123", h2)
