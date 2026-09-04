from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


class _EngineHolder:
    engine: Engine | None = None
    factory: sessionmaker | None = None


_holder = _EngineHolder()


def _make_engine(url: str) -> Engine:
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _record):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def get_engine() -> Engine:
    if _holder.engine is None:
        _holder.engine = _make_engine(get_settings().database_url_resolved)
    return _holder.engine


def get_session_factory() -> sessionmaker:
    if _holder.factory is None:
        _holder.factory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _holder.factory


def configure_engine(url: str) -> None:
    """Point the app at a different database (used by tests)."""
    _holder.engine = _make_engine(url)
    _holder.factory = sessionmaker(
        bind=_holder.engine, autoflush=False, expire_on_commit=False, future=True
    )


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
