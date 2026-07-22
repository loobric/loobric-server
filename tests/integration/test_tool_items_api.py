# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for ToolItem bulk API endpoints.

Tests bulk-first design: all operations accept arrays.

Assumptions:
- POST /api/v1/tool-items - Create (bulk)
- GET /api/v1/tool-items - List/query with filters
- PUT /api/v1/tool-items - Update (bulk) with version checking
- DELETE /api/v1/tool-items - Delete (bulk)
- Single operations use array with one element
- Partial success supported with per-item results
- Multi-tenant: Users only access their own data
- Requires authentication
"""
import pytest
from datetime import datetime, UTC


@pytest.mark.integration
def test_bulk_create_tool_items(client, db_session):
    """Test bulk create of tool items.
    
    Assumptions:
    - Accepts array of items
    - Returns success count and per-item results
    - Auto-generates IDs if not provided
    - Sets user_id from authenticated user
    - Sets created_by/updated_by from authenticated user
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    
    # Create user and session
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    items = [
        {
            "type": "cutting_tool",
            "manufacturer": "Kennametal",
            "product_code": "KC725M",
            "description": "10mm end mill",
            "geometry": {"diameter": 10.0, "length": 75.0, "flutes": 4}
        },
        {
            "type": "holder",
            "manufacturer": "Haimer",
            "product_code": "A63.055.10",
            "description": "HSK63 holder"
        }
    ]
    
    client.cookies.set("session", session_id)
    
    response = client.post(
        "/api/v1/tool-items",
        json={"items": items}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 2
    assert len(data["results"]) == 2
    assert data["error_count"] == 0
    
    # Verify IDs were generated
    for result in data["results"]:
        assert "id" in result
        assert result["user_id"] == user.id
        assert result["created_by"] == user.id


@pytest.mark.integration
def test_single_create_uses_array(client, db_session):
    """Test single item create using array with one element.
    
    Assumptions:
    - Same endpoint handles single and bulk
    - Array with one element for single operation
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    client.cookies.set("session", session_id)
    
    response = client.post(
        "/api/v1/tool-items",
        json={
            "items": [{
                "type": "cutting_tool",
                "manufacturer": "Sandvik",
                "product_code": "R390"
            }]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1


@pytest.mark.integration
def test_create_requires_authentication(client):
    """Test that create requires authentication.
    
    Assumptions:
    - Returns 401 without valid session
    """
    response = client.post(
        "/api/v1/tool-items",
        json={"items": [{"type": "cutting_tool"}]}
    )
    
    assert response.status_code == 401


@pytest.mark.integration
def test_create_validates_required_fields(client, db_session):
    """Test validation of required fields during create.
    
    Assumptions:
    - Type is required
    - Returns error for invalid items
    - Partial success: valid items created, invalid items return errors
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    items = [
        {
            "type": "cutting_tool",
            "manufacturer": "Kennametal",
            "product_code": "KC725M"
        },
        {
            # Missing required 'type' field
            "manufacturer": "Sandvik",
            "product_code": "R390"
        }
    ]
    
    client.cookies.set("session", session_id)
    
    response = client.post(
        "/api/v1/tool-items",
        json={"items": items}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 1
    assert data["error_count"] == 1
    assert len(data["errors"]) == 1
    assert "type" in data["errors"][0]["message"].lower()


@pytest.mark.integration
def test_bulk_read_tool_items(client, db_session):
    """Test bulk read/list of tool items.
    
    Assumptions:
    - GET returns array of items
    - Filters by user_id automatically (multi-tenant)
    - Supports pagination
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolItem
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create some items
    for i in range(5):
        item = ToolItem(
            type="cutting_tool",
            manufacturer="Test",
            product_code=f"TEST-{i:03d}",
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
        db_session.add(item)
    db_session.commit()
    
    client.cookies.set("session", session_id)
    
    response = client.get(
        "/api/v1/tool-items"
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert "items" in data
    assert len(data["items"]) == 5
    assert data["total"] == 5


@pytest.mark.integration
def test_read_filters_by_user(client, db_session):
    """Test that users only see their own tool items.
    
    Assumptions:
    - Multi-tenant isolation
    - User A cannot see User B's items
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolItem
    
    user1 = create_user(db_session, "user1@example.com", "Password123")
    user2 = create_user(db_session, "user2@example.com", "Password123")
    
    # Create items for each user
    for user in [user1, user2]:
        item = ToolItem(
            type="cutting_tool",
            manufacturer="Test",
            product_code=f"TEST-{user.id}",
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
        db_session.add(item)
    db_session.commit()
    
    # User1 session
    session1 = create_session(user1.id)
    client.cookies.set("session", session1)
    
    response = client.get(
        "/api/v1/tool-items"
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Should only see their own item
    assert len(data["items"]) == 1
    assert data["items"][0]["user_id"] == user1.id


@pytest.mark.integration
def test_bulk_update_tool_items(client, db_session):
    """Test bulk update of tool items.
    
    Assumptions:
    - PUT accepts array of items with IDs
    - Updates version field
    - Checks version for conflicts (optimistic locking)
    - Returns success count and per-item results
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolItem
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create items
    item1 = ToolItem(
        type="cutting_tool",
        manufacturer="Kennametal",
        product_code="KC725M",
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=1
    )
    item2 = ToolItem(
        type="holder",
        manufacturer="Haimer",
        product_code="A63",
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=1
    )
    db_session.add_all([item1, item2])
    db_session.commit()
    
    # Update both items
    updates = [
        {
            "id": item1.id,
            "version": 1,
            "description": "Updated description 1"
        },
        {
            "id": item2.id,
            "version": 1,
            "description": "Updated description 2"
        }
    ]
    
    client.cookies.set("session", session_id)
    
    response = client.put(
        "/api/v1/tool-items",
        json={"items": updates}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 2
    assert data["error_count"] == 0
    
    # Verify version incremented
    for result in data["results"]:
        assert result["version"] == 2


@pytest.mark.integration
def test_update_detects_version_conflict(client, db_session):
    """Test optimistic locking detects version conflicts.
    
    Assumptions:
    - Update with wrong version number fails
    - Returns error with conflict details
    - Partial success: other items still updated
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolItem
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create item
    item = ToolItem(
        type="cutting_tool",
        manufacturer="Kennametal",
        product_code="KC725M",
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=2  # Current version is 2
    )
    db_session.add(item)
    db_session.commit()
    
    # Try to update with old version
    client.cookies.set("session", session_id)
    
    response = client.put(
        "/api/v1/tool-items",
        json={
            "items": [{
                "id": item.id,
                "version": 1,  # Wrong version
                "description": "Updated"
            }]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 0
    assert data["error_count"] == 1
    assert len(data["errors"]) == 1
    assert "version" in data["errors"][0]["message"].lower() or "conflict" in data["errors"][0]["message"].lower()


@pytest.mark.integration
def test_update_rejects_other_users_items(client, db_session):
    """Test that users cannot update other users' items.
    
    Assumptions:
    - Multi-tenant isolation enforced
    - Returns error for items not owned by user
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolItem
    
    user1 = create_user(db_session, "user1@example.com", "Password123")
    user2 = create_user(db_session, "user2@example.com", "Password123")
    
    # Create item for user1
    item = ToolItem(
        type="cutting_tool",
        manufacturer="Test",
        product_code="TEST-001",
        user_id=user1.id,
        created_by=user1.id,
        updated_by=user1.id,
        version=1
    )
    db_session.add(item)
    db_session.commit()
    
    # User2 tries to update user1's item
    session2 = create_session(user2.id)
    client.cookies.set("session", session2)
    
    response = client.put(
        "/api/v1/tool-items",
        json={
            "items": [{
                "id": item.id,
                "version": 1,
                "description": "Hacked!"
            }]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 0
    assert data["error_count"] == 1


@pytest.mark.integration
def test_bulk_delete_tool_items(client, db_session):
    """Test bulk delete of tool items.
    
    Assumptions:
    - DELETE accepts array of IDs
    - Returns success count
    - Soft delete or hard delete (TBD)
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolItem
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create items
    items = []
    for i in range(3):
        item = ToolItem(
            type="cutting_tool",
            manufacturer="Test",
            product_code=f"TEST-{i:03d}",
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
        items.append(item)
        db_session.add(item)
    db_session.commit()
    
    # Delete first two items
    client.cookies.set("session", session_id)
    
    response = client.request(
        "DELETE",
        "/api/v1/tool-items",
        json={"ids": [items[0].id, items[1].id]}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 2
    assert data["error_count"] == 0
    
    # Verify deletion
    remaining = db_session.query(ToolItem).filter(ToolItem.user_id == user.id).all()
    assert len(remaining) == 1


@pytest.mark.integration
def test_delete_rejects_other_users_items(client, db_session):
    """Test that users cannot delete other users' items.
    
    Assumptions:
    - Multi-tenant isolation enforced
    - Returns error for items not owned by user
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolItem
    
    user1 = create_user(db_session, "user1@example.com", "Password123")
    user2 = create_user(db_session, "user2@example.com", "Password123")
    
    # Create item for user1
    item = ToolItem(
        type="cutting_tool",
        manufacturer="Test",
        product_code="TEST-001",
        user_id=user1.id,
        created_by=user1.id,
        updated_by=user1.id
    )
    db_session.add(item)
    db_session.commit()
    
    # User2 tries to delete user1's item
    session2 = create_session(user2.id)
    client.cookies.set("session", session2)
    
    response = client.request(
        "DELETE",
        "/api/v1/tool-items",
        json={"ids": [item.id]}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 0
    assert data["error_count"] == 1
    
    # Verify item still exists
    db_session.refresh(item)
    assert item is not None


@pytest.mark.integration
def test_query_with_filters(client, db_session):
    """Test querying items with filters.
    
    Assumptions:
    - Supports filtering by type, manufacturer, product_code
    - Supports search in description
    - Returns filtered results
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolItem
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create items with different types
    items = [
        ToolItem(type="cutting_tool", manufacturer="Kennametal", product_code="KC1", 
                 user_id=user.id, created_by=user.id, updated_by=user.id),
        ToolItem(type="holder", manufacturer="Haimer", product_code="H1",
                 user_id=user.id, created_by=user.id, updated_by=user.id),
        ToolItem(type="cutting_tool", manufacturer="Sandvik", product_code="S1",
                 user_id=user.id, created_by=user.id, updated_by=user.id),
    ]
    db_session.add_all(items)
    db_session.commit()
    
    # Filter by type
    client.cookies.set("session", session_id)
    
    response = client.get(
        "/api/v1/tool-items?type=cutting_tool"
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert len(data["items"]) == 2
    for item in data["items"]:
        assert item["type"] == "cutting_tool"


@pytest.mark.integration
def test_pagination(client, db_session):
    """Test pagination of results.
    
    Assumptions:
    - Supports limit and offset parameters
    - Returns total count
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolItem
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create 25 items
    for i in range(25):
        item = ToolItem(
            type="cutting_tool",
            manufacturer="Test",
            product_code=f"TEST-{i:03d}",
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
        db_session.add(item)
    db_session.commit()
    
    # Get first page
    client.cookies.set("session", session_id)
    
    response = client.get(
        "/api/v1/tool-items?limit=10&offset=0"
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert len(data["items"]) == 10
    assert data["total"] == 25
    assert data["limit"] == 10
    assert data["offset"] == 0


@pytest.mark.integration
def test_get_single_tool_item_success(client, db_session):
    """Test retrieving a single tool item by ID."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolItem

    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)

    # Create item
    item = ToolItem(
        type="cutting_tool",
        manufacturer="Test",
        product_code="ABC-123",
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(item)
    db_session.commit()

    response = client.get(
        f"/api/v1/tool-items/{item.id}",
        cookies={"session": session_id}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == item.id
    assert data["product_code"] == "ABC-123"


@pytest.mark.integration
def test_get_single_tool_item_not_found_other_user(client, db_session):
    """Test that accessing another user's tool item returns 404."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolItem

    owner = create_user(db_session, "owner@example.com", "Password123")
    other = create_user(db_session, "other@example.com", "Password123")
    session_id = create_session(other.id)

    # Create owner's item
    item = ToolItem(
        type="holder",
        manufacturer="Test",
        product_code="OWNER-1",
        user_id=owner.id,
        created_by=owner.id,
        updated_by=owner.id
    )
    db_session.add(item)
    db_session.commit()

    response = client.get(
        f"/api/v1/tool-items/{item.id}",
        cookies={"session": session_id}
    )
    assert response.status_code == 404
