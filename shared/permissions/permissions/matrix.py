# LOCATION: shared/permissions/permissions/matrix.py

"""
FIX-M3: single canonical PERMISSION_MATRIX, imported by every service's
middleware instead of each service inventing its own inline role checks
(Section 4a: "define one canonical PERMISSION_MATRIX dict... and import
it into every service's middleware. Never define permissions inline in
routes.").

The dict below reproduces Section 4a's entries VERBATIM (covering
routes that belong to services not built yet — Job Service, Interview
Service, etc. — so the matrix is already complete for when they arrive).
`ADDITIONAL_ENTRIES` below it covers routes that exist TODAY in
Tenant Service but weren't anticipated when Section 4a was written
(tenant selection, invite acceptance) plus one naming difference (see
its comment) — both dicts are merged into the single `PERMISSION_MATRIX`
services actually import.
"""

from __future__ import annotations

import re

# ─────────────────────────────────────────────────────────────────────────
# Verbatim from Section 4a of the project plan.
# Format: "HTTP_METHOD /path/pattern": [allowed_roles]
# Use "public" for no auth required, "*" for any authenticated user.
# ─────────────────────────────────────────────────────────────────────────
_SECTION_4A_MATRIX: dict[str, str | list[str]] = {
    # Auth — public
    "POST /signup/company":           "public",
    "POST /signup/candidate":         "public",
    "POST /auth/login":               "public",
    "POST /auth/verify-otp":          "public",
    "POST /auth/refresh":             "public",
    "GET  /public/jobs":              "public",
    "GET  /health":                   "public",

    # Tenant management
    "GET  /tenant/settings":          ["company_admin"],
    "PUT  /tenant/settings":          ["company_admin"],
    "POST /tenant/invite":            ["company_admin"],
    "GET  /tenant/members":           ["company_admin", "recruiter"],
    "PUT  /tenant/members/{id}/role": ["company_admin"],
    "DELETE /tenant/members/{id}":    ["company_admin"],

    # Job management
    "POST /jobs":                     ["company_admin", "recruiter"],
    "PUT  /jobs/{id}":                ["company_admin", "recruiter"],
    "DELETE /jobs/{id}":              ["company_admin", "recruiter"],
    "GET  /jobs":                     ["company_admin", "recruiter"],
    "GET  /jobs/{id}":                ["company_admin", "recruiter"],
    "GET  /jobs/{id}/applicants":     ["company_admin", "recruiter"],
    "POST /jobs/{id}/apply":          ["candidate"],
    "GET  /jobs/{id}/my-application": ["candidate"],

    # Interview management
    "POST /interviews/schedule":      ["company_admin", "recruiter"],
    "GET  /interviews/{id}":          ["company_admin", "recruiter",
                                       "interviewer", "observer"],
    "GET  /interviews/{id}/scorecard":["company_admin", "recruiter", "interviewer"],
    "POST /interviews/{id}/join":     ["company_admin", "recruiter",
                                       "interviewer", "observer", "candidate"],

    # Candidate pipeline actions
    "POST /applications/{id}/advance":["company_admin", "recruiter"],
    "POST /applications/{id}/reject": ["company_admin", "recruiter"],

    # Scorecard
    "GET  /scorecards/{id}":          ["company_admin", "recruiter", "interviewer"],
    "POST /scorecards/{id}/approve":  ["interviewer"],
    "GET  /scorecards/{id}/pdf":      ["company_admin", "recruiter", "interviewer"],

    # Candidate profile (self only — enforced in service layer too)
    "GET  /profile":                  ["candidate"],
    "PUT  /profile":                  ["candidate"],
    "POST /profile/resume":           ["candidate"],

    # System admin only
    "GET  /admin/*":                  ["system_admin"],
    "POST /admin/migrate-tenants":    ["system_admin"],
    "POST /admin/suspend-tenant":     ["system_admin"],
}

# ─────────────────────────────────────────────────────────────────────────
# Entries for routes that exist TODAY (M2/M3) but weren't in Section 4a's
# original listing, since that section was written before these exact
# endpoints were designed:
#   - Section 4a wrote "POST /tenant/invite" (singular). Our actual
#     implementation (invite_routes.py) uses the plural collection-style
#     "/tenant/invites" (POST to create, /tenant/invites/accept to
#     accept). Both spellings are kept in the merged matrix below: the
#     singular for fidelity to the plan text, the plural because it's
#     what's actually deployed and enforced.
#   - "/tenant/invites/accept" and "/tenant/select" didn't exist in
#     Section 4a at all (tenant selection wasn't designed yet).
# ─────────────────────────────────────────────────────────────────────────
_ADDITIONAL_ENTRIES: dict[str, str | list[str]] = {
    "POST /tenant/invites":           ["company_admin"],
    "POST /tenant/invites/accept":    "*",  # any authenticated user may attempt to accept an invite addressed to them
    "POST /tenant/select":            "*",  # any authenticated user may attempt to select a tenant they claim membership in
}

PERMISSION_MATRIX: dict[str, str | list[str]] = {**_SECTION_4A_MATRIX, **_ADDITIONAL_ENTRIES}


def _path_pattern_to_regex(path: str) -> re.Pattern:
    """Converts a matrix path pattern (e.g. '/jobs/{id}', '/admin/*')
    into a compiled regex matching real request paths."""
    is_prefix_wildcard = path.endswith("/*")
    body = path[:-2] if is_prefix_wildcard else path

    segments = [seg for seg in body.split("/") if seg != ""]
    regex_parts = [
        r"[^/]+" if seg.startswith("{") and seg.endswith("}") else re.escape(seg)
        for seg in segments
    ]
    pattern = "^/" + "/".join(regex_parts)
    pattern += r"(/.*)?$" if is_prefix_wildcard else r"$"
    return re.compile(pattern)


# Precompiled once at import time: list of (method, compiled_regex, allowed)
_COMPILED_MATRIX: list[tuple[str, re.Pattern, str | list[str]]] = []
for _raw_key, _allowed in PERMISSION_MATRIX.items():
    _method, _path = _raw_key.split(None, 1)
    _COMPILED_MATRIX.append((_method.strip().upper(), _path_pattern_to_regex(_path.strip()), _allowed))


def find_matrix_entry(method: str, path: str) -> str | list[str] | None:
    """Returns the matrix's `allowed` value ('public', '*', or a role
    list) for the first pattern matching (method, path), or None if no
    entry matches at all -- callers should treat "no entry" as DENY by
    default (fail closed), never as an implicit allow."""
    method = method.upper()
    for entry_method, regex, allowed in _COMPILED_MATRIX:
        if entry_method == method and regex.match(path):
            return allowed
    return None


def is_allowed(method: str, path: str, role: str | None) -> bool:
    """True if `role` may call `method path` per the matrix.

    Fails closed: an unmapped route is always denied, never silently
    allowed.

    IMPORTANT: this function assumes the caller has ALREADY been
    authenticated (a valid token was decoded) before `role` is passed
    in — `role=None` here means "an authenticated identity whose role
    happens to be unset" (e.g. a candidate, or a company_user who
    hasn't selected a tenant yet), NOT "no identity at all". Whether a
    route requires authentication in the first place is the `"public"`
    vs everything-else distinction, enforced by the caller (e.g.
    `enforce_permission_matrix()` in tenant_service/auth_dependency.py)
    before `is_allowed` is ever consulted.
    """
    allowed = find_matrix_entry(method, path)
    if allowed is None:
        return False
    if allowed == "public":
        return True
    if allowed == "*":
        return True  # any authenticated identity, role irrelevant -- including role=None
    return role in allowed
