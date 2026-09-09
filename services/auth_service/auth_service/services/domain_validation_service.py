# LOCATION: services/auth_service/auth_service/services/domain_validation_service.py

"""
Corporate email domain validation (Section 10d / Task C).

Two independent checks, both must pass:
  1. Domain is NOT in the public-webmail blocklist (gmail, outlook, ...)
  2. Domain has at least one MX record (proves it can actually receive
     mail -- catches typos and fake domains like "acme-corp-typo.com")

Domain uniqueness against already-registered tenants is NOT this
module's job -- that's enforced by TenantRepository.create_pending()
(Section 1: "After OTP verification, domain is locked to the tenant").
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_BLOCKLIST_PATH = Path(__file__).resolve().parent.parent / "data" / "public_domain_blocklist.txt"


def _load_blocklist() -> frozenset[str]:
    domains = set()
    with open(_BLOCKLIST_PATH, "r") as f:
        for line in f:
            line = line.strip().lower()
            if line and not line.startswith("#"):
                domains.add(line)
    return frozenset(domains)


_BLOCKLIST = _load_blocklist()


class DomainValidationError(Exception):
    """Base class for all domain validation failures."""


class PublicEmailDomainError(DomainValidationError):
    def __init__(self, domain: str):
        super().__init__(
            f"'{domain}' is a public email provider. Please sign up with your "
            "company's corporate email address."
        )
        self.domain = domain


class DomainHasNoMailServerError(DomainValidationError):
    def __init__(self, domain: str):
        super().__init__(
            f"'{domain}' does not appear to be able to receive email (no MX record found). "
            "Please check for typos."
        )
        self.domain = domain


@dataclass
class DomainValidationResult:
    domain: str
    is_valid: bool


def extract_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower()


def is_public_email_domain(domain: str) -> bool:
    return domain.lower() in _BLOCKLIST


def check_mx_record(domain: str) -> bool:
    """Returns True if `domain` has at least one MX record.

    Imports dnspython lazily so this module stays importable in
    environments/tests without network access or the dependency
    installed; tests monkeypatch this function directly instead of
    hitting real DNS.
    """
    import dns.resolver

    try:
        answers = dns.resolver.resolve(domain, "MX")
        return len(answers) > 0
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return False
    except Exception:  # noqa: BLE001 - any DNS-layer failure means "can't confirm it's valid"
        return False


class DomainValidationService:
    """Wraps both checks. Call `validate(email)` — raises a specific
    `DomainValidationError` subclass on failure, returns the domain
    string on success."""

    def __init__(self, mx_checker=check_mx_record):
        self._mx_checker = mx_checker

    def validate(self, email: str) -> str:
        domain = extract_domain(email)

        if is_public_email_domain(domain):
            raise PublicEmailDomainError(domain)

        if not self._mx_checker(domain):
            raise DomainHasNoMailServerError(domain)

        return domain
