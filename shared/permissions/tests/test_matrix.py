# LOCATION: shared/permissions/tests/test_matrix.py

from permissions import PERMISSION_MATRIX, find_matrix_entry, is_allowed


def test_public_route_allows_unauthenticated():
    assert is_allowed("POST", "/signup/candidate", None) is True
    assert is_allowed("GET", "/health", None) is True


def test_public_route_allows_any_role_too():
    assert is_allowed("GET", "/health", "candidate") is True


def test_exact_match_role_required():
    assert is_allowed("POST", "/tenant/invite", "company_admin") is True
    assert is_allowed("POST", "/tenant/invite", "recruiter") is False
    assert is_allowed("POST", "/tenant/invite", None) is False


def test_multi_role_entry():
    assert is_allowed("GET", "/jobs", "company_admin") is True
    assert is_allowed("GET", "/jobs", "recruiter") is True
    assert is_allowed("GET", "/jobs", "candidate") is False


def test_path_param_pattern_matches_real_ids():
    assert is_allowed("GET", "/jobs/abc-123-def", "recruiter") is True
    assert is_allowed("PUT", "/jobs/00000000-0000-0000-0000-000000000000", "company_admin") is True


def test_path_param_pattern_does_not_match_extra_segments():
    # /jobs/{id} should not match /jobs/abc/extra
    assert find_matrix_entry("GET", "/jobs/abc/extra") is None


def test_wildcard_prefix_matches_any_depth():
    assert is_allowed("GET", "/admin/tenants", "system_admin") is True
    assert is_allowed("GET", "/admin/tenants/123/detail", "system_admin") is True
    assert is_allowed("GET", "/admin/tenants", "company_admin") is False


def test_star_role_means_any_authenticated_caller_regardless_of_role():
    """'*' is only reached after authentication already succeeded (see
    is_allowed's docstring) -- role=None here means 'an authenticated
    candidate/company_user with no tenant role yet', which is exactly
    who needs to call /tenant/select or /tenant/invites/accept. It must
    NOT be rejected."""
    assert is_allowed("POST", "/tenant/select", "recruiter") is True
    assert is_allowed("POST", "/tenant/select", None) is True
    assert is_allowed("POST", "/tenant/invites/accept", None) is True


def test_unmapped_route_denied_by_default_fail_closed():
    assert find_matrix_entry("GET", "/totally/not/a/real/route") is None
    assert is_allowed("GET", "/totally/not/a/real/route", "system_admin") is False


def test_method_mismatch_denied():
    # /jobs exists for GET/POST but not for DELETE without an {id}
    assert find_matrix_entry("DELETE", "/jobs") is None


def test_both_invite_route_spellings_present():
    """FIX-M3 note: Section 4a wrote the singular '/tenant/invite'; our
    actual implementation uses the plural '/tenant/invites'. Both are
    in the matrix (see matrix.py's _ADDITIONAL_ENTRIES comment)."""
    assert "POST /tenant/invite" in PERMISSION_MATRIX
    assert "POST /tenant/invites" in PERMISSION_MATRIX


def test_candidate_pipeline_actions_restricted_to_staff():
    assert is_allowed("POST", "/applications/123/advance", "recruiter") is True
    assert is_allowed("POST", "/applications/123/advance", "candidate") is False


def test_scorecard_approval_is_interviewer_only():
    assert is_allowed("POST", "/scorecards/123/approve", "interviewer") is True
    assert is_allowed("POST", "/scorecards/123/approve", "company_admin") is False
    assert is_allowed("POST", "/scorecards/123/approve", "recruiter") is False
