# LOCATION: services/migration_service/migration_service/main.py

"""
Migration Service entrypoint.

Two modes, matching Section 3 of the project plan:

  1. `python -m migration_service.main serve`
     Headless Kafka consumer — listens for tenant.signup_initiated and
     provisions each tenant DB as events arrive.

  2. `python -m migration_service.main migrate-all-tenants`
     System-admin-triggered command (FIX-M1's exact naming) — iterates
     tenant_migrations and runs pending migrations across every ACTIVE
     tenant DB. Intended to be invoked manually or from an internal
     admin tool, NEVER from the API request path. `migrate-all` is
     still accepted as an alias for anyone who scripted against the
     earlier name.

This service has no FastAPI routes (Section 6: "migration_service/ ←
no routes (headless Kafka consumer + CLI commands)").
"""

from __future__ import annotations

import asyncio
import logging
import sys

from insynchire_events import EventProducer, Topics, subscribe
from insynchire_events.schemas import TenantSignupInitiatedEvent

from shared.db import make_engine, make_session_factory
from shared.db.crypto import get_crypto

from .config import get_config
from .services import ProvisioningService, run_pending_migrations_for_all_tenants

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("migration_service")


def _build_provisioning_service(producer: EventProducer) -> ProvisioningService:
    config = get_config()
    engine = make_engine(config.global_db_dsn)
    session_factory = make_session_factory(engine)
    return ProvisioningService(
        config=config,
        global_session_factory=session_factory,
        publish=producer.publish,
        crypto=get_crypto(),
    )


async def serve() -> None:
    """Run forever, consuming tenant.signup_initiated events."""
    producer = EventProducer()
    await producer.start()
    provisioning_service = _build_provisioning_service(producer)

    async def handle(event: TenantSignupInitiatedEvent) -> None:
        logger.info("provisioning tenant_id=%s subdomain=%s", event.tenant_id, event.subdomain)
        await provisioning_service.handle_signup(event)
        logger.info("provisioned tenant_id=%s successfully", event.tenant_id)

    try:
        await subscribe(
            Topics.TENANT_SIGNUP_INITIATED.value,
            handle,
            group_id=get_config().kafka_consumer_group,
        )
    finally:
        await producer.stop()


async def migrate_all() -> None:
    """System-admin CLI command: bring every ACTIVE tenant DB up to the
    current head revision of the tenant migration suite."""
    config = get_config()
    engine = make_engine(config.global_db_dsn)
    session_factory = make_session_factory(engine)

    results = await run_pending_migrations_for_all_tenants(
        config=config, global_session_factory=session_factory
    )
    changed = [r for r in results if r["changed"]]
    logger.info(
        "migrate-all complete: %d tenants checked, %d updated", len(results), len(changed)
    )
    for r in changed:
        logger.info(
            "  tenant_id=%s %s -> %s", r["tenant_id"], r["previous_version"], r["new_version"]
        )


def main() -> None:
    valid_commands = {"serve", "migrate-all-tenants", "migrate-all"}
    if len(sys.argv) < 2 or sys.argv[1] not in valid_commands:
        print("Usage: python -m migration_service.main [serve|migrate-all-tenants]")
        sys.exit(1)

    command = sys.argv[1]
    if command == "serve":
        asyncio.run(serve())
    elif command in {"migrate-all-tenants", "migrate-all"}:
        asyncio.run(migrate_all())


if __name__ == "__main__":
    main()
