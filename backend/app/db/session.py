"""SQLAlchemy engine and session factory.

Sync SQLAlchemy is used on purpose: the same models and services are shared by
FastAPI (sync endpoints run in a threadpool) and Celery workers (sync), so
there is one code path to test.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine: Engine | None = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_settings().database_url, pool_pre_ping=True, pool_size=5, max_overflow=5
        )
        SessionLocal.configure(bind=_engine)
    return _engine


def get_db() -> Iterator[Session]:
    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
