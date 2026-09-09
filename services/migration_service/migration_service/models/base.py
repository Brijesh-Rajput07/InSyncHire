# LOCATION: services/migration_service/migration_service/models/base.py

"""Declarative base shared by all insynchire_global ORM models."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
