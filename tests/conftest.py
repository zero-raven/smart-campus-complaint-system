"""Pytest fixtures.

Two database strategies are supported:

* default   - run against smart_campus_test (schema + seed loaded from
              database/schema.sql and database/seed.sql)
* live      - run against the development database (never destructive)

The MongoDB database is namespaced to *_test and dropped between sessions so a
test run cannot pollute development event data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Tests must never touch the development MongoDB database.
os.environ.setdefault("MONGO_TEST_DB", "smart_campus_test")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DEBUG", "false")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.core.config import get_settings  # noqa: E402
from backend.core.mongo import get_client  # noqa: E402
from backend.core.security import hash_password  # noqa: E402
from backend.models.complaint import Base  # noqa: E402

settings = get_settings()
TEST_DB_NAME = settings.mongo_test_db


@pytest.fixture(scope="session")
def engine():
    """Create the test database schema from database/schema.sql.

    The authoritative DDL is applied rather than Base.metadata.create_all().
    The two are not interchangeable: create_all() builds columns from ORM
    Python-side defaults, which emit no server_default. A column such as
    department.is_active is 'NOT NULL DEFAULT TRUE' in the DDL but becomes
    'NOT NULL' under create_all, so any INSERT that relies on the database
    default - including all of database/seed.sql - then fails. Applying the real
    schema also means the tests exercise the DDL that actually ships.

    pgcrypto is created by schema.sql, so no extension is needed here.
    """
    import subprocess

    psql = [
        "psql", "-U", settings.postgres_user, "-h", settings.postgres_host,
        "-d", settings.postgres_test_db, "-v", "ON_ERROR_STOP=1", "-q",
        "-c", "DROP SCHEMA public CASCADE; CREATE SCHEMA public; "
              f"GRANT ALL ON SCHEMA public TO {settings.postgres_user};",
    ]
    env = {**os.environ, "PGPASSWORD": settings.postgres_password}
    reset = subprocess.run(psql, env=env, capture_output=True, text=True)
    if reset.returncode != 0:
        pytest.fail(f"Could not reset test schema: {reset.stderr}")

    for script in ("schema.sql", "seed.sql"):
        cmd = psql[:-2] + ["-f", str(PROJECT_ROOT / "database" / script)]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            pytest.fail(f"{script} failed: {result.stderr}")

    eng = create_engine(settings.test_database_url, echo=False, future=True)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def db_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture()
def db(db_session_factory):
    """Transactional session: rolled back after every test."""
    session = db_session_factory()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture(scope="session")
def seeded(engine, db_session_factory):
    """Reference data is already loaded by the engine fixture.

    Kept as a named fixture so tests can declare their dependency on seeded
    reference data explicitly rather than depending on engine's side effects.
    """
    session = db_session_factory()
    yield session
    session.close()


@pytest.fixture(scope="session")
def mongo_db():
    """A clean MongoDB database for the test session."""
    client = get_client()
    client.drop_database(TEST_DB_NAME)
    db = client[TEST_DB_NAME]
    yield db
    client.drop_database(TEST_DB_NAME)


@pytest.fixture(scope="session")
def users(db_session_factory):
    """One user per role, created once per test session.

    Session-scoped because the fixture commits: a function-scoped version
    would commit the same usernames on every test and the second test would
    fail on the app_user_username_key unique constraint. Callers receive
    detached instances, which is all the auth fixtures need.
    """
    from backend.models.people import AppUser, Staff
    from backend.models.reference import Department

    session = db_session_factory()
    try:
        password = hash_password("Test@1234")
        dept = session.query(Department).filter(Department.dept_code == "CIVIL").one()

        created = {}
        for role in ("STUDENT", "STAFF", "ADMIN", "VIEWER"):
            user = AppUser(
                username=f"test_{role.lower()}",
                email=f"test_{role.lower()}@rvce.edu.in",
                password_hash=password,
                full_name=f"Test {role}",
                role=role,
                dept_id=dept.dept_id if role in ("STAFF", "ADMIN") else None,
            )
            session.add(user)
            session.flush()
            created[role] = user

        session.add(
            Staff(
                user_id=created["STAFF"].user_id,
                dept_id=dept.dept_id,
                designation="Test Engineer",
            )
        )
        session.commit()

        for user in created.values():
            session.refresh(user)
            session.expunge(user)
        return created
    finally:
        session.close()


@pytest.fixture()
def client(db_session_factory, seeded, mongo_db):
    """FastAPI TestClient wired to the test database and test MongoDB."""
    from fastapi.testclient import TestClient

    import backend.core.database as database_module
    import backend.core.mongo as mongo_module
    from backend.main import app

    # Point the app's session factory at the test engine.
    database_module.SessionLocal = db_session_factory

    # Point every Mongo helper at the test database.
    original_get_database = mongo_module.get_database
    mongo_module.get_database = lambda db_name=None: mongo_db

    import backend.api.v1.complaints as complaints_api
    import backend.api.v1.dashboard as dashboard_api

    complaints_api.get_database = lambda: mongo_db
    dashboard_api.get_database = lambda: mongo_db

    # The attachment router resolves the GridFS database name from settings at
    # import time. Tests must not write photo bytes into the development
    # MongoDB database, so the name is forced to the test database.
    import backend.api.v1.attachments as attachments_api
    import backend.services.attachment_service as attachment_service_module

    attachments_api._settings = type(
        "TestSettings", (), {"mongo_db": mongo_db.name, "mongo_test_db": mongo_db.name}
    )()

    with TestClient(app) as test_client:
        test_client.mongo_db = mongo_db
        yield test_client

    mongo_module.get_database = original_get_database


@pytest.fixture()
def auth_headers(client, users):
    """Bearer headers for each seeded test role."""

    def _login(username: str, password: str = "Test@1234") -> dict[str, str]:
        response = client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return {
        "STUDENT": _login("test_student"),
        "STAFF": _login("test_staff"),
        "ADMIN": _login("test_admin"),
        "VIEWER": _login("test_viewer"),
    }
