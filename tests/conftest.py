# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Pytest configuration and shared fixtures.

This module provides test fixtures that are shared across the test suite.

Assumptions:
- Tests run with authentication ENABLED by default (production-like)
- Tests that need auth disabled must use the disable_auth fixture
- Each test gets a fresh TestClient instance
- Database fixtures use in-memory SQLite
"""
import pytest
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from loobric_server.main import create_app
from loobric_server.database.schema import Base


@pytest.fixture
def app():
    """Create a FastAPI application instance for testing.
    
    Returns:
        FastAPI: Application instance with test configuration
        
    Assumptions:
    - Auth is disabled for testing
    - Uses in-memory or test database (when implemented)
    """
    return create_app()


@pytest.fixture
def client(db_session, request):
    """Create test client sharing the same database session.
    
    Args:
        db_session: Shared database session fixture
        request: Pytest request object to check for disable_auth marker
        
    Returns:
        TestClient: FastAPI test client
        
    Assumptions:
    - Shares database session with tests
    - Overrides get_db dependency to use shared session
    - Auth disabled if test uses disable_auth fixture
    """
    from loobric_server.main import create_app
    from loobric_server.api.auth import get_db
    from loobric_server.config import settings
    
    # Store original auth_enabled value
    original_auth_enabled = settings.auth_enabled
    
    # Check if disable_auth fixture was used
    if 'disable_auth' in request.fixturenames:
        settings.auth_enabled = False
    
    app = create_app()
    
    # Override get_db to return the shared session
    def override_get_db():
        try:
            yield db_session
        finally:
            pass  # Don't close, let the fixture handle it
    
    app.dependency_overrides[get_db] = override_get_db
    
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
    
    # Restore original auth setting
    settings.auth_enabled = original_auth_enabled


@pytest.fixture
def minimal_backup():
    """Minimal backup fixture with single admin user.
    
    Returns:
        dict: Backup with one user, no tool data
        
    Assumptions:
    - Used for testing basic functionality
    - Single admin user for testing
    """
    from tests.fixtures.sample_data import create_minimal_backup
    return create_minimal_backup()


@pytest.fixture
def single_user_backup():
    """Single user backup fixture with tool data.
    
    Returns:
        dict: Backup with one user, API keys, and tool items
        
    Assumptions:
    - Used for testing user-level operations
    - Includes realistic tool data
    """
    from tests.fixtures.sample_data import create_single_user_backup
    return create_single_user_backup()


@pytest.fixture
def multi_user_backup():
    """Multi-user backup fixture with tool data.
    
    Returns:
        dict: Backup with multiple users, each with their own data
        
    Assumptions:
    - Used for testing multi-tenant isolation
    - Each user has their own tool items and API keys
    """
    from tests.fixtures.sample_data import create_multi_user_backup
    return create_multi_user_backup()


@pytest.fixture
def db_with_sample_data(db_session):
    """Database session pre-loaded with sample data.
    
    Args:
        db_session: Base database session fixture
        
    Returns:
        Session: Database session with sample data loaded
        
    Assumptions:
    - Uses backup/restore to load data
    - Includes single user with tool items
    - Useful for integration tests
    """
    from loobric_server.backup import restore_backup
    from tests.fixtures.sample_data import create_single_user_backup
    
    backup = create_single_user_backup()
    restore_backup(db_session, backup)
    
    return db_session


@pytest.fixture
def disable_auth(monkeypatch):
    """Disable authentication for tests that need it.
    
    Use this fixture for tests that specifically need to test
    unauthenticated behavior or legacy tests that haven't been
    updated to use proper authentication.
    
    Example:
        def test_something(client, disable_auth):
            # Auth is disabled for this test
            response = client.get("/api/endpoint")
    """
    monkeypatch.setenv("AUTH_ENABLED", "false")


@pytest.fixture
def admin_headers(client, db_session):
    """Create admin user and return authorization headers.
    
    Returns:
        dict: Headers with session cookie for admin user
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    
    # Create admin user
    admin = create_user(db_session, "admin@example.com", "AdminPass123")
    admin.is_admin = True
    admin.role = "admin"
    db_session.commit()
    
    session_id = create_session(admin.id)
    return {"Cookie": f"session={session_id}"}


@pytest.fixture
def user_headers(client, db_session):
    """Create regular user and return authorization headers.
    
    Returns:
        dict: Headers with session cookie for regular user
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    
    # Create regular user (ensure it's not admin)
    user = create_user(db_session, "user@example.com", "UserPass123")
    user.is_admin = False
    user.role = "user"
    db_session.commit()
    
    session_id = create_session(user.id)
    return {"Cookie": f"session={session_id}"}


@pytest.fixture
def manufacturer_headers(client, db_session):
    """Create manufacturer user and return authorization headers.
    
    Manufacturer users can create catalog ToolItems that regular users can copy.
    
    Returns:
        dict: Headers with session cookie for manufacturer user
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    
    # Create manufacturer user
    manufacturer = create_user(db_session, "manufacturer@example.com", "MfgPass123")
    manufacturer.role = "manufacturer"
    manufacturer.manufacturer_profile = {
        "company_name": "Test Manufacturing Co",
        "website": "https://test-mfg.com"
    }
    db_session.commit()
    
    session_id = create_session(manufacturer.id)
    return {"Cookie": f"session={session_id}"}


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing.
    
    Returns:
        Session: SQLAlchemy session
        
    Assumptions:
    - Uses in-memory SQLite for fast tests
    - StaticPool keeps connection alive across threads
    - check_same_thread=False allows TestClient to use same connection
    - Schema is created fresh for each test
    - Session is closed after test
    """
    from sqlalchemy.pool import StaticPool
    from loobric_server.database.schema import init_db
    
    # Create an in-memory SQLite database
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    
    # Initialize the database with all tables
    init_db(engine)
    
    # Create a new session for testing
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    
    try:
        yield session
    finally:
        session.close()
