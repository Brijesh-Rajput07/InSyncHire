# LOCATION: services/job_service/job_service/main.py

"""
Job Service FastAPI app (M5). Pure HTTP API -- no Kafka consumer of its
own (unlike Tenant Service or User Profile Service), since nothing in
this milestone's scope needs to react to another service's events.

Run locally with:
  uvicorn job_service.main:app --reload --port 8004
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .dependencies import _event_producer
from .routes import application_jobs_router, applications_router, job_router, public_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _event_producer.start()
    yield
    await _event_producer.stop()


app = FastAPI(title="InSyncHire Job Service", version="0.1.0", lifespan=lifespan)

app.include_router(job_router, tags=["jobs"])
app.include_router(application_jobs_router, tags=["applications"])
app.include_router(applications_router, tags=["applications"])
app.include_router(public_router, tags=["public"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "job_service"}