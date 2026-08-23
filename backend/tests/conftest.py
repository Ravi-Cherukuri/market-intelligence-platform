"""Isolated SQLite fixtures for the pilot backend's black-box tests."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_settings as dependency_settings
from app.config import Settings
from app.database import Base, get_db
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url="sqlite://",
        whatsapp_app_secret="test-app-secret",
        whatsapp_verify_token="test-verify-token",
        conversation_timeout_minutes=30,
    )


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    """A single connection keeps SQLite's in-memory schema visible to the API."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(
    session_factory: sessionmaker[Session], settings: Settings
) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_db() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    # Webhook routes bind this dependency directly; admin routes reach the
    # same cached settings through `dependency_settings`.
    app.dependency_overrides[dependency_settings] = lambda: settings
    try:
        # Deliberately avoid TestClient's context manager: application lifespan
        # owns the production engine, while these tests own the SQLite fixture.
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()

