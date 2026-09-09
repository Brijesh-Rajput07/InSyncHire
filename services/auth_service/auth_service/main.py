# LOCATION: services/auth_service/auth_service/main.py

"""
Auth Service FastAPI app.

Handles all /auth/* and /signup/* routes (Section 3: "API Gateway /
Auth Service ... Owns cookie issuance, token validation, OTP flow.
Corporate domain validation logic lives here"). These routes are also
in the connection-routing middleware's skip-list (Task E, once built)
since they run before a user is authenticated.

Run locally with:
  uvicorn auth_service.main:app --reload --port 8001
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .dependencies import _event_producer
from .routes import auth_router, signup_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _event_producer.start()
    yield
    await _event_producer.stop()


app = FastAPI(title="InSyncHire Auth Service", version="0.1.0", lifespan=lifespan)

app.include_router(signup_router, tags=["signup"])
app.include_router(auth_router, tags=["auth"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "auth_service"}
