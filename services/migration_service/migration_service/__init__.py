# LOCATION: services/migration_service/migration_service/__init__.py

"""Migration Service -- headless Kafka consumer + CLI, no HTTP routes.

Provisions new tenant databases in response to tenant.signup_initiated
and runs the system-admin-triggered "migrate all tenants" command.
See Section 4 (M1) and Task B of the project plan.
"""
