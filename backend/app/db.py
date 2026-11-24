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
    _add_missing_columns(engine)
    return engine


def _add_missing_columns(engine: Engine) -> None:
    """Add columns introduced after a database was first created.

    create_all() only creates missing tables, so a column added to a model
    later has to be added to existing databases here. Only nullable columns
    with no default are added this way.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl_type}'))


def get_session() -> Iterator[Session]:
    if SessionLocal is None:
        init_db()
    assert SessionLocal is not None
    with SessionLocal() as session:
        yield session
