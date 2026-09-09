# LOCATION: shared/auth-tokens/tests/conftest.py

"""Shared test helper: isolated fakeredis instance per test."""

from __future__ import annotations

from fakeredis import aioredis as fake_aioredis


def build_fake_redis():
    return fake_aioredis.FakeRedis(decode_responses=True)
