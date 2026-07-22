# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Integration tests for audit log query API endpoints.

Tests role-based access control:
- Admins can query all logs
- Regular users can only query their own logs
"""

import pytest
from fastapi.testclient import TestClient
from loobric_server.main import app
from loobric_server.database.schema import Base, User, AuditLog
from loobric_server.api.auth import get_db
from loobric_server.auth.user import create_user
from loobric_server.audit import create_audit_log
from loobric_server.config import settings
from sqlalchemy import create_engine
from datetime import datetime, UTC
from uuid import uuid4


@pytest.fixture
def test_db():
    """Create a fresh test database for each test."""
    engine = create_engine(settings.database_url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def admin_user(test_db):
    """Create an admin user (first user is auto-admin)."""
    db = next(get_db())
    user = create_user(db, "admin@example.com", "password123")
    # First user is automatically admin
    db.close()
    return user


@pytest.fixture
def regular_user(test_db, admin_user):
    """Create a regular user (depends on admin_user to ensure it's not first)."""
    db = next(get_db())
    user = create_user(db, "user@example.com", "password123")
    # Second user is not admin by default
    db.close()
    return user


@pytest.fixture
def other_user(test_db, admin_user):
    """Create another regular user (depends on admin_user to ensure it's not first)."""
    db = next(get_db())
    user = create_user(db, "other@example.com", "password123")
    db.close()
    return user


@pytest.fixture
def sample_logs(test_db, regular_user, other_user):
    """Create sample audit logs for different users."""
    db = next(get_db())
    
    # Create logs for regular_user
    for i in range(5):
        create_audit_log(
            session=db,
            user_id=regular_user.id,
            operation="CREATE",
            entity_type="ToolItem",
            entity_id=str(uuid4()),
            changes={"test": f"data_{i}"},
            result="success"
        )
    
    # Create logs for other_user
    for i in range(3):
        create_audit_log(
            session=db,
            user_id=other_user.id,
            operation="UPDATE",
            entity_type="ToolAssembly",
            entity_id=str(uuid4()),
            changes={"test": f"other_{i}"},
            result="success"
        )
    
    db.close()


def login_user(client, email, password):
    """Helper to login and return session cookie."""
    response = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password
    })
    assert response.status_code == 200
    return response.cookies.get("session")


class TestAuditLogQueryAsRegularUser:
    """Test audit log queries as regular user."""
    
    def test_user_can_query_own_logs(self, client, regular_user, sample_logs):
        """Regular user can query their own logs."""
        session = login_user(client, "user@example.com", "password123")
        
        response = client.get(
            "/api/v1/audit-logs",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert len(data["logs"]) == 5
        
        # All logs should belong to regular_user
        for log in data["logs"]:
            assert log["user_id"] == regular_user.id
    
    def test_user_cannot_query_other_user_logs(self, client, regular_user, other_user, sample_logs):
        """Regular user cannot see other user's logs."""
        session = login_user(client, "user@example.com", "password123")
        
        response = client.get(
            f"/api/v1/audit-logs?user_id={other_user.id}",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should only see their own logs, not other_user's
        assert len(data["logs"]) == 5
        for log in data["logs"]:
            assert log["user_id"] == regular_user.id
    
    def test_user_can_filter_by_operation(self, client, regular_user, sample_logs):
        """Regular user can filter their logs by operation."""
        session = login_user(client, "user@example.com", "password123")
        
        response = client.get(
            "/api/v1/audit-logs?operation=CREATE",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) == 5
        
        for log in data["logs"]:
            assert log["operation"] == "CREATE"
    
    def test_user_can_filter_by_entity_type(self, client, regular_user, sample_logs):
        """Regular user can filter their logs by entity type."""
        session = login_user(client, "user@example.com", "password123")
        
        response = client.get(
            "/api/v1/audit-logs?entity_type=ToolItem",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) == 5
        
        for log in data["logs"]:
            assert log["entity_type"] == "ToolItem"
    
    def test_user_can_limit_results(self, client, regular_user, sample_logs):
        """Regular user can limit number of results."""
        session = login_user(client, "user@example.com", "password123")
        
        response = client.get(
            "/api/v1/audit-logs?limit=3",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) == 3


class TestAuditLogQueryAsAdmin:
    """Test audit log queries as admin user."""
    
    def test_admin_can_query_all_logs(self, client, admin_user, sample_logs):
        """Admin user can query all logs from all users."""
        session = login_user(client, "admin@example.com", "password123")
        
        response = client.get(
            "/api/v1/audit-logs",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        # Should see logs from both regular_user (5) and other_user (3)
        assert len(data["logs"]) == 8
    
    def test_admin_can_filter_by_specific_user(self, client, admin_user, other_user, sample_logs):
        """Admin can filter logs by specific user."""
        session = login_user(client, "admin@example.com", "password123")
        
        response = client.get(
            f"/api/v1/audit-logs?user_id={other_user.id}",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) == 3
        
        for log in data["logs"]:
            assert log["user_id"] == other_user.id
    
    def test_admin_can_filter_by_operation(self, client, admin_user, sample_logs):
        """Admin can filter logs by operation."""
        session = login_user(client, "admin@example.com", "password123")
        
        response = client.get(
            "/api/v1/audit-logs?operation=UPDATE",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) == 3
        
        for log in data["logs"]:
            assert log["operation"] == "UPDATE"
    
    def test_admin_can_filter_by_entity_type(self, client, admin_user, sample_logs):
        """Admin can filter logs by entity type."""
        session = login_user(client, "admin@example.com", "password123")
        
        response = client.get(
            "/api/v1/audit-logs?entity_type=ToolAssembly",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["logs"]) == 3
        
        for log in data["logs"]:
            assert log["entity_type"] == "ToolAssembly"


class TestAuditLogQueryUnauthenticated:
    """Test audit log queries without authentication."""
    
    def test_unauthenticated_request_fails(self, client, sample_logs):
        """Unauthenticated requests are rejected."""
        response = client.get("/api/v1/audit-logs")
        
        assert response.status_code == 401
