from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def db_path() -> Path:
    return Path(os.environ.get("CROWDTRACKER_DB", "data/crowdtracker.db"))


def make_engine(url: str | None = None) -> Engine:
    if url is None:
        path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return engine


engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def init_db(url: str | None = None) -> Engine:
    """Create the engine and tables. Safe to call more than once."""
    global engine, SessionLocal
    from . import models  # noqa: F401  (register tables)

    engine = make_engine(url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    return engine


def get_session() -> Iterator[Session]:
    if SessionLocal is None:
        init_db()
    assert SessionLocal is not None
    with SessionLocal() as session:
        yield session
