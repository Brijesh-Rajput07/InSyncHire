# LOCATION: services/auth_service/tests/test_domain_validation_service.py

"""
Tests for DomainValidationService. The MX check is stubbed via a fake
checker function instead of hitting real DNS -- no network access
needed, and results are deterministic.
"""

import pytest

from auth_service.services.domain_validation_service import (
    DomainHasNoMailServerError,
    DomainValidationService,
    PublicEmailDomainError,
    extract_domain,
    is_public_email_domain,
)


def test_extract_domain():
    assert extract_domain("alice@Acme.COM") == "acme.com"


def test_public_domains_are_blocked():
    for domain in ["gmail.com", "yahoo.com", "outlook.com", "icloud.com", "protonmail.com"]:
        assert is_public_email_domain(domain) is True


def test_corporate_domain_not_in_blocklist():
    assert is_public_email_domain("acme-corp.com") is False


def test_validate_rejects_public_domain():
    service = DomainValidationService(mx_checker=lambda d: True)
    with pytest.raises(PublicEmailDomainError):
        service.validate("alice@gmail.com")


def test_validate_rejects_domain_with_no_mx_record():
    service = DomainValidationService(mx_checker=lambda d: False)
    with pytest.raises(DomainHasNoMailServerError):
        service.validate("alice@totally-fake-typo-domain-xyz.com")


def test_validate_accepts_good_corporate_domain():
    service = DomainValidationService(mx_checker=lambda d: True)
    domain = service.validate("alice@acme-corp.com")
    assert domain == "acme-corp.com"
