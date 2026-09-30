"""Database connections; schema changes are managed exclusively by Alembic."""
from __future__ import annotations

import os
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker


def database_url():
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    return URL.create(
        "postgresql+psycopg", username=os.getenv("POSTGRES_USER", "postbank"),
        password=os.getenv("POSTGRES_PASSWORD"), host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")), database=os.getenv("POSTGRES_DB", "postbank"),
    )


def make_engine(url=None):
    engine = create_engine(url or database_url(), pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine


def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
