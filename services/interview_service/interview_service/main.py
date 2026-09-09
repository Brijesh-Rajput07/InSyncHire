# LOCATION: services/interview_service/interview_service/main.py

"""
Interview Service FastAPI app (M8 HTTP routes + M9 WebSocket gateway).
Pure HTTP API plus one WebSocket route -- no Kafka consumer of its own
(it PUBLISHES `interview.scheduled` and, as of M9, `interview.completed`;
it doesn't consume anything).

Run locally with:
  uvicorn interview_service.main:app --reload --port 8005
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .dependencies import _event_producer
from .routes import interview_router
from .ws_gateway import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _event_producer.start()
    yield
    await _event_producer.stop()


app = FastAPI(title="InSyncHire Interview Service", version="0.1.0", lifespan=lifespan)

app.include_router(interview_router, tags=["interviews"])
app.include_router(ws_router, tags=["live-room"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "interview_service"}