# LOCATION: shared/shared-db/shared/__init__.py

"""
Namespace package root for InSyncHire's shared, cross-service libraries.

Currently contains `shared.db` (async engine/session helpers, RLS
activation, GUID column type, connection-string encryption). Future
additions from Section 6 of the project plan -- `shared.config`,
`shared.exceptions`, `shared.middleware` -- will live alongside `db` here
under this same installable package.
"""
