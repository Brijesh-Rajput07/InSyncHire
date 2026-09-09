# LOCATION: shared/auth-tokens/README.md

# insynchire-auth-tokens

Shared token issuance/verification package (Section 10c). Extracted
from Auth Service during M3, because Tenant Service also needs to:

1. **Verify** who's calling (decode the `insynchire_access` cookie to
   get `user_id`), and
2. **Issue** a new, tenant-scoped token once it's confirmed the caller
   has a membership in the tenant they're selecting (something Auth
   Service can't do — it doesn't know about tenant memberships, those
   live in per-tenant databases).

Rather than Tenant Service reimplementing the encrypted-JWT scheme
(and risking it silently drifting out of sync with Auth Service's
version — a security-sensitive thing to get wrong twice), both services
import the exact same `TokenService` from here.

## Install

```bash
pip install -e shared/auth-tokens
```

## Critical: every service needs the SAME keys

`TokenService` is configured with an RS256 keypair and a Fernet key.
**Every service that touches tokens (Auth Service, Tenant Service, and
any future one) must be configured with the exact same keypair and the
exact same Fernet key** — these are shared system secrets, not
per-service ones. If Tenant Service used a different keypair, it
couldn't verify tokens Auth Service issued, and vice versa.

In practice: set `JWT_PRIVATE_KEY_PATH` / `JWT_PUBLIC_KEY_PATH` /
`TOKEN_PAYLOAD_ENCRYPTION_KEY` to the same files/values in every
service's `.env`.

## Usage

```python
from auth_tokens import TokenService, generate_rsa_keypair_pem

service = TokenService(
    private_key_pem=...,   # same across all services
    public_key_pem=...,    # same across all services
    fernet_key=...,        # same across all services
    redis=redis_client,    # same Redis instance (denylist is shared state)
)

# Verify an incoming cookie
payload = await service.decode_and_verify(cookie_value, expected_type="access")
print(payload.user_id, payload.tenant_id, payload.role)

# Issue a new token (e.g. after confirming tenant membership)
tokens = await service.issue_token_pair(
    user_id=user_id, tenant_id=tenant_id, org_id=org_id, role="company_admin",
    fingerprint=session_fingerprint(ip, user_agent),
)
```

## Tests

```bash
cd shared/auth-tokens
python -m pytest -q
```
Expected: `9 passed`.
