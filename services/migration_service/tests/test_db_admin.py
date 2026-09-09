# LOCATION: services/migration_service/tests/test_db_admin.py

"""
Tests for the pure, dependency-free helper functions in db_admin.py.

create_tenant_database() and run_tenant_migration_suite() require a
real Postgres instance and are NOT exercised here -- they're covered by
mocking in test_provisioning_service.py, and should additionally be run
against a real local Postgres before deploying (see README.md's
"integration test" section).
"""

import uuid

from migration_service.db_admin import build_tenant_db_name, render_dsn
from migration_service.main import main as cli_main


def test_build_tenant_db_name_is_deterministic_and_ddl_safe():
    tenant_id = uuid.uuid4()
    name1 = build_tenant_db_name(tenant_id)
    name2 = build_tenant_db_name(tenant_id)
    assert name1 == name2
    assert name1 == f"tenant_{tenant_id.hex}_db"
    # no dashes -- safe as a bare Postgres identifier
    assert "-" not in name1


def test_build_tenant_db_name_differs_per_tenant():
    a, b = build_tenant_db_name(uuid.uuid4()), build_tenant_db_name(uuid.uuid4())
    assert a != b


def test_render_dsn_substitutes_db_name():
    template = "postgresql+asyncpg://user:pass@localhost:5433/{db_name}"
    result = render_dsn(template, "tenant_abc123_db")
    assert result == "postgresql+asyncpg://user:pass@localhost:5433/tenant_abc123_db"


def test_cli_rejects_unknown_command(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["main.py", "not-a-real-command"])
    try:
        cli_main()
        raised = False
    except SystemExit:
        raised = True
    assert raised
    assert "migrate-all-tenants" in capsys.readouterr().out  # FIX-M1's canonical command name in usage text


def test_cli_accepts_canonical_and_legacy_migrate_command_names(monkeypatch):
    """FIX-M1 renames the command to migrate-all-tenants; migrate-all
    stays accepted as a legacy alias rather than being a breaking change."""
    calls = []
    monkeypatch.setattr("migration_service.main.asyncio.run", lambda coro: calls.append(coro) or coro.close())

    monkeypatch.setattr("sys.argv", ["main.py", "migrate-all-tenants"])
    cli_main()

    monkeypatch.setattr("sys.argv", ["main.py", "migrate-all"])
    cli_main()

    assert len(calls) == 2
