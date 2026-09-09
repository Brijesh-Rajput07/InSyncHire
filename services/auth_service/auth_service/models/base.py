# LOCATION: services/auth_service/auth_service/models/base.py

"""
Two separate declarative bases because insynchire_global and users_db
are different physical Postgres databases (Section 1) — SQLAlchemy
metadata must never mix tables that live in different DBs under one
Base, or Alembic autogenerate/migrations get confused about what
belongs where.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class GlobalBase(DeclarativeBase):
    """Tables in insynchire_global that this service reads/writes."""


class UsersDbBase(DeclarativeBase):
    """Tables in users_db that this service reads/writes."""
