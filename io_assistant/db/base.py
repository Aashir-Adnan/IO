from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str):
    return create_engine(database_url, future=True)


def make_session_factory(engine_or_connection):
    return sessionmaker(
        bind=engine_or_connection,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False, future=True)
