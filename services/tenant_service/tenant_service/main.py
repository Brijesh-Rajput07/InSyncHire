# LOCATION: services/tenant_service/tenant_service/main.py

"""
Tenant Service FastAPI app.

Unlike Migration Service (pure headless consumer) or Auth Service (pure
HTTP API), Tenant Service is BOTH: it serves `/tenant/*` HTTP routes
AND consumes `tenant.created` in the background to bootstrap
company_admin. Both run in the same process via the lifespan's
background task, which is simpler to operate than a separate consumer
process for one lightweight handler — revisit this if the consumer
side ever needs independent scaling.

Run locally with:
  uvicorn tenant_service.main:app --reload --port 8002
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from insynchire_events import Topics, subscribe
from insynchire_events.schemas import TenantCreatedEvent

from .config import get_config
from .dependencies import _event_producer, get_tenant_provisioning_consumer_service
from .routes import invite_router, selection_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("tenant_service.main")

_consumer_task: asyncio.Task | None = None


async def _run_tenant_created_consumer() -> None:
    consumer_service = get_tenant_provisioning_consumer_service()

    async def handle(event: TenantCreatedEvent) -> None:
        logger.info("bootstrapping company_admin for tenant_id=%s", event.tenant_id)
        await consumer_service.handle_tenant_created(event)

    await subscribe(
        Topics.TENANT_CREATED.value, handle, group_id=get_config().kafka_consumer_group
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _consumer_task
    await _event_producer.start()
    _consumer_task = asyncio.create_task(_run_tenant_created_consumer())
    yield
    if _consumer_task is not None:
        _consumer_task.cancel()
    await _event_producer.stop()


app = FastAPI(title="InSyncHire Tenant Service", version="0.1.0", lifespan=lifespan)

app.include_router(invite_router, tags=["invites"])
app.include_router(selection_router, tags=["tenant-selection"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "tenant_service"}
