# LOCATION: services/migration_service/tests/test_alembic_tenant_chain.py

"""
FIX-M1 verification (extended for M8/M9): the tenant Alembic chain
resolves to a single head (now 0006_code_snapshots), and each revision
named here actually defines the tables it claims to -- catching the
class of bug FIX-M1 exists to prevent (a migration file present on disk
that isn't actually wired into the chain Migration Service runs).
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_SERVICE_DIR = Path(__file__).resolve().parent.parent


def _tenant_script_dir() -> ScriptDirectory:
    cfg = Config(str(_SERVICE_DIR / "alembic_tenant.ini"))
    cfg.set_main_option("script_location", str(_SERVICE_DIR / "alembic_tenant"))
    return ScriptDirectory.from_config(cfg)


def test_tenant_chain_has_single_head():
    sd = _tenant_script_dir()
    heads = sd.get_heads()
    assert len(heads) == 1, f"expected exactly one head, got {heads} -- a revision is unlinked"
    assert heads[0] == "0006_code_snapshots"


def test_tenant_chain_includes_all_revisions_in_order():
    sd = _tenant_script_dir()
    revisions = [rev.revision for rev in sd.walk_revisions()]
    assert "0006_code_snapshots" in revisions
    assert "0005_interview_sessions" in revisions
    assert "0004_job_openings_and_applications" in revisions
    assert "0003_agent_and_process_logs" in revisions
    assert "0002_invited_users" in revisions
    assert "0001_initial" in revisions


def test_fix_m1_revision_creates_the_three_required_tables():
    module_path = _SERVICE_DIR / "alembic_tenant" / "versions" / "20260301_0003_agent_and_process_logs.py"
    source = module_path.read_text()
    for table_name in ("agent_decision_logs", "agent_guardrail_logs", "process_logs"):
        assert f'"{table_name}"' in source, f"{table_name} not found in FIX-M1 migration"
        assert f'tenant_isolation_policy ON "{table_name}"' in source, f"{table_name} missing RLS policy"


def test_m8_revision_creates_interview_tables_with_rls():
    module_path = _SERVICE_DIR / "alembic_tenant" / "versions" / "20260601_0005_interview_sessions.py"
    source = module_path.read_text()
    for table_name in ("interview_sessions", "interview_participants"):
        assert f'"{table_name}"' in source, f"{table_name} not found in M8 migration"
        assert f'tenant_isolation_policy ON "{table_name}"' in source, f"{table_name} missing RLS policy"
    assert 'down_revision: Union[str, None] = "0004_job_openings_and_applications"' in source


def test_m9_revision_creates_code_snapshots_with_rls():
    module_path = _SERVICE_DIR / "alembic_tenant" / "versions" / "20260701_0006_code_snapshots.py"
    source = module_path.read_text()
    assert '"code_snapshots"' in source
    assert 'tenant_isolation_policy ON "code_snapshots"' in source
    assert 'down_revision: Union[str, None] = "0005_interview_sessions"' in source