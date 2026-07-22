# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for change detection API endpoints.

Tests version-based and timestamp-based sync with authentication.

Assumptions:
- Clients track last_synced_version or last_synced_timestamp
- Regular users only see their own changes
- Admin users see all changes
- Changes ordered by version/timestamp for sequential processing
"""
import pytest
from fastapi.testclient import TestClient
from loobric_server.main import app
from loobric_server.database.schema import Base, ToolInstanceRecord, User
from loobric_server.api.auth import get_db
from loobric_server.auth.user import create_user
from loobric_server.config import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from datetime import datetime, UTC, timedelta
from urllib.parse import quote


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
    db.close()
    return user


@pytest.fixture
def regular_user(test_db, admin_user):
    """Create a regular user."""
    db = next(get_db())
    user = create_user(db, "user@example.com", "password123")
    db.close()
    return user


@pytest.fixture
def other_user(test_db, admin_user):
    """Create another regular user."""
    db = next(get_db())
    user = create_user(db, "other@example.com", "password123")
    db.close()
    return user


def login_user(client, email, password):
    """Helper to login and return session cookie."""
    response = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": password
    })
    assert response.status_code == 200
    return response.cookies.get("session")


@pytest.fixture
def sample_tool_items(test_db, regular_user, other_user):
    """Create sample v2 tool instance records with different versions."""
    db = next(get_db())

    # Records for regular_user
    for i in range(3):
        record = ToolInstanceRecord(
            id=f"item-user-{i}",
            canonical={"manufacturer": f"Manufacturer {i}"},
            clients={},
            version=i + 2,  # versions 2, 3, 4
            user_id=regular_user.id,
            created_by=regular_user.id,
            updated_by=regular_user.id,
            updated_at=datetime.now(UTC) - timedelta(minutes=30 - i * 10)
        )
        db.add(record)

    # Records for other_user
    for i in range(2):
        record = ToolInstanceRecord(
            id=f"item-other-{i}",
            canonical={"manufacturer": f"Other Manufacturer {i}"},
            clients={},
            version=i + 2,
            user_id=other_user.id,
            created_by=other_user.id,
            updated_by=other_user.id,
            updated_at=datetime.now(UTC) - timedelta(minutes=20 - i * 10)
        )
        db.add(record)

    db.commit()
    db.close()


class TestChangesByVersion:
    """Test version-based change detection."""
    
    def test_get_changes_since_version(self, client, regular_user, sample_tool_items):
        """Test retrieving changes since specific version."""
        session = login_user(client, "user@example.com", "password123")
        
        response = client.get(
            "/api/v1/changes/tool_instance_records/since-version?since_version=2",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["entity_type"] == "tool_instance_records"
        assert data["sync_method"] == "version"
        assert data["count"] == 2  # versions 3 and 4
        assert len(data["changes"]) == 2
        
        # Verify ordering by version
        versions = [change["version"] for change in data["changes"]]
        assert versions == [3, 4]
    
    def test_get_all_changes_from_version_zero(self, client, regular_user, sample_tool_items):
        """Test that version 0 returns all entities."""
        session = login_user(client, "user@example.com", "password123")
        
        response = client.get(
            "/api/v1/changes/tool_instance_records/since-version?since_version=0",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return all 3 items for regular_user
        assert data["count"] == 3
    
    def test_user_only_sees_own_changes(self, client, regular_user, sample_tool_items):
        """Test that regular users only see their own changes."""
        session = login_user(client, "user@example.com", "password123")
        
        response = client.get(
            "/api/v1/changes/tool_instance_records/since-version?since_version=0",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should only see their own 3 items, not other_user's 2 items
        assert data["count"] == 3
        for change in data["changes"]:
            assert change["user_id"] == regular_user.id
    
    def test_admin_sees_all_changes(self, client, admin_user, sample_tool_items):
        """Test that admin users see changes from all users."""
        session = login_user(client, "admin@example.com", "password123")
        
        response = client.get(
            "/api/v1/changes/tool_instance_records/since-version?since_version=0",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should see all 5 items (3 from regular_user + 2 from other_user)
        assert data["count"] == 5
    
    def test_max_version_included_in_response(self, client, regular_user, sample_tool_items):
        """Test that max_version is included for sync state tracking."""
        session = login_user(client, "user@example.com", "password123")
        
        response = client.get(
            "/api/v1/changes/tool_instance_records/since-version?since_version=0",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert "max_version" in data
        assert data["max_version"] == 4  # Highest version for regular_user
    
    def test_limit_parameter_works(self, client, regular_user, sample_tool_items):
        """Test that limit parameter restricts results."""
        session = login_user(client, "user@example.com", "password123")
        
        response = client.get(
            "/api/v1/changes/tool_instance_records/since-version?since_version=0&limit=2",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["count"] == 2
        assert len(data["changes"]) == 2


class TestChangesByTimestamp:
    """Test timestamp-based change detection."""
    
    def test_get_changes_since_timestamp(self, client, regular_user, sample_tool_items):
        """Test retrieving changes since specific timestamp."""
        session = login_user(client, "user@example.com", "password123")
        
        # Get changes from 25 minutes ago
        since_time = (datetime.now(UTC) - timedelta(minutes=25)).isoformat()
        encoded_time = quote(since_time)
        
        response = client.get(
            f"/api/v1/changes/tool_instance_records/since-timestamp?since_timestamp={encoded_time}",
            cookies={"session": session}
        )
        
        if response.status_code != 200:
            print(f"Error: {response.status_code}, Response: {response.text}")
        assert response.status_code == 200
        data = response.json()
        
        assert data["entity_type"] == "tool_instance_records"
        assert data["sync_method"] == "timestamp"
        assert data["count"] >= 1  # At least some recent changes
    
    def test_timestamp_ordering(self, client, regular_user, sample_tool_items):
        """Test that changes are ordered by timestamp."""
        session = login_user(client, "user@example.com", "password123")
        
        since_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        encoded_time = quote(since_time)
        
        response = client.get(
            f"/api/v1/changes/tool_instance_records/since-timestamp?since_timestamp={encoded_time}",
            cookies={"session": session}
        )
        
        if response.status_code != 200:
            print(f"Error: {response.status_code}, Response: {response.text}")
        assert response.status_code == 200
        data = response.json()
        
        # Verify ordering by timestamp
        if data["count"] > 1:
            timestamps = [change["updated_at"] for change in data["changes"]]
            assert timestamps == sorted(timestamps)


class TestMaxVersionEndpoint:
    """Test max version endpoint."""
    
    def test_get_max_version(self, client, regular_user, sample_tool_items):
        """Test retrieving max version for entity type."""
        session = login_user(client, "user@example.com", "password123")
        
        response = client.get(
            "/api/v1/changes/tool_instance_records/max-version",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["entity_type"] == "tool_instance_records"
        assert data["max_version"] == 4
    
    def test_max_version_returns_zero_when_empty(self, client, regular_user, test_db):
        """Test max version returns 0 when no entities exist."""
        session = login_user(client, "user@example.com", "password123")
        
        response = client.get(
            "/api/v1/changes/tool_instance_records/max-version",
            cookies={"session": session}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["max_version"] == 0


class TestInvalidRequests:
    """Test error handling."""
    
    def test_invalid_entity_type(self, client, regular_user, test_db):
        """Test that invalid entity type returns 400."""
        session = login_user(client, "user@example.com", "password123")
        
        response = client.get(
            "/api/v1/changes/invalid_type/since-version?since_version=0",
            cookies={"session": session}
        )
        
        assert response.status_code == 400
        assert "Invalid entity_type" in response.json()["detail"]
    
    def test_unauthenticated_request_fails(self, client, test_db):
        """Test that unauthenticated requests are rejected."""
        response = client.get(
            "/api/v1/changes/tool_instance_records/since-version?since_version=0"
        )
        
        assert response.status_code == 401


class TestMultipleEntityTypes:
    """Test that changes API works with different entity types."""
    
    def test_supports_multiple_entity_types(self, client, regular_user, test_db):
        """Test that API supports all entity types."""
        session = login_user(client, "user@example.com", "password123")
        
        entity_types = [
            "machine_records",
            "tool_instance_records",
            "tool_catalog_records",
            "tool_table_entry_records",
            "tool_set_records",
        ]
        
        for entity_type in entity_types:
            response = client.get(
                f"/api/v1/changes/{entity_type}/since-version?since_version=0",
                cookies={"session": session}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["entity_type"] == entity_type
