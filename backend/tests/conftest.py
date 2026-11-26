"""Test fixtures.

Tests run against a real PostgreSQL + pgvector (no SQLite stand-in), because
the graph traversal is a recursive CTE and embeddings use pgvector types.

* The schema is built once per session with Alembic, so migrations are tested too.
* Each test runs inside an outer transaction that is rolled back afterwards;
  service code that calls `commit()` only releases a SAVEPOINT. Tests are
  isolated and fast without truncating tables.
"""

import os

os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+psycopg://specforge:specforge@localhost:5433/specforge_test"
)
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ.setdefault("REDIS_URL", "redis://localhost:6380/15")
os.environ["ENVIRONMENT"] = "test"

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command
from app.core.security import hash_password
from app.db.session import get_db
from app.main import create_app
from app.models import User

DB_URL = os.environ["TEST_DATABASE_URL"]
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_database() -> None:
    url = make_url(DB_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def engine():  # type: ignore[no-untyped-def]
    _ensure_database()
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.set_main_option("sqlalchemy.url", DB_URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(DB_URL)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine) -> Iterator[Session]:  # type: ignore[no-untyped-def]
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------- helpers

PASSWORD = "correct-horse-battery"


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    counter = {"n": 0}

    def _make(*, admin: bool = False, email: str | None = None) -> User:
        counter["n"] += 1
        user = User(
            email=email or f"user{counter['n']}@example.com",
            display_name=f"User {counter['n']}",
            password_hash=hash_password(PASSWORD),
            is_admin=admin,
        )
        db.add(user)
        db.commit()
        return user

    return _make


@pytest.fixture
def login(client: TestClient) -> Callable[[User], dict[str, str]]:
    def _login(user: User) -> dict[str, str]:
        r = client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _login


@pytest.fixture
def api(client: TestClient) -> Callable[..., Any]:
    """Tiny helper: api("post", "/projects", headers, json=...) -> response."""

    def _call(method: str, path: str, headers: dict[str, str] | None = None, **kw: Any) -> Any:
        return getattr(client, method)(f"/api/v1{path}", headers=headers or {}, **kw)

    return _call
