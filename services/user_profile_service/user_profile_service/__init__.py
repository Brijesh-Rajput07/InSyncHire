# LOCATION: services/user_profile_service/user_profile_service/__init__.py

"""User Profile Service (M4) -- owns users_db.

Consumes `user.registered` (published by Auth Service since FIX-M2) to
create the `user_profiles` row for every new candidate, and exposes
`/profile/*` endpoints for candidates to manage their own profile and
resumes. See Section 4 (M4) of the project plan.
"""