# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for tag-based access control on tool items.

Tests tag enforcement across CRUD operations for tool items.

Assumptions:
- API keys can have tags that restrict access to resources
- Resources (tool items) can have tags
- Access granted if any API key tag matches any resource tag
- Empty API key tags = no restrictions (access all resources with proper scopes)
- Empty resource tags = accessible to all keys with proper scopes
- Admin scope (admin:*) bypasses tag checks
- Session auth bypasses tag checks (user owns all their resources)
"""
import pytest
from loobric_server.database.schema import ToolItem


@pytest.mark.integration
def test_create_tool_item_with_api_key_tags(client, db_session):
    """Test creating tool items with API key that has tags."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create API key with tags
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read", "write:items"],
        tags=["mill-3", "production"]
    )
    
    # Test 1: Create tool item with allowed tags
    response = client.post(
        "/api/v1/tool-items",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "type": "cutting_tool",
                "manufacturer": "Sandvik",
                "product_code": "R390-11 T3 08M-PM",
                "tags": ["mill-3"]
            }]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    assert data["results"][0]["tags"] == ["mill-3"]
    
    # Test 2: Create tool item with unauthorized tag fails
    response = client.post(
        "/api/v1/tool-items",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "type": "holder",
                "manufacturer": "Haas",
                "tags": ["lathe-1"]
            }]
        }
    )
    
    assert response.status_code == 200  # Partial success response
    data = response.json()
    assert data["success_count"] == 0
    assert data["error_count"] == 1
    assert "not authorized" in data["errors"][0]["message"].lower()


@pytest.mark.integration
def test_list_tool_items_filtered_by_api_key_tags(client, db_session):
    """Test listing tool items is filtered by API key tags."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create tool items with different tags
    tool_items = [
        ToolItem(
            type="cutting_tool",
            manufacturer="Sandvik",
            tags=["mill-3", "production"],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        ),
        ToolItem(
            type="holder",
            manufacturer="Haas",
            tags=["lathe-1"],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        ),
        ToolItem(
            type="insert",
            manufacturer="Kennametal",
            tags=["production"],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        ),
    ]
    for item in tool_items:
        db_session.add(item)
    db_session.commit()
    
    # Create API key with mill-3 tag
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read"],
        tags=["mill-3"]
    )
    
    # List tool items with tagged API key
    response = client.get(
        "/api/v1/tool-items",
        headers={"Authorization": f"Bearer {api_key_plain}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Should only see tool items with mill-3 tag
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["manufacturer"] == "Sandvik"


@pytest.mark.integration
def test_get_tool_item_with_tag_access(client, db_session):
    """Test getting single tool item with tag-based access control."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create tool item with tags
    tool_item = ToolItem(
        type="cutting_tool",
        manufacturer="Sandvik",
        tags=["mill-3", "production"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(tool_item)
    db_session.commit()
    
    # Test 1: API key with matching tag can access
    api_key_mill_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read"],
        tags=["mill-3"]
    )
    
    response = client.get(
        f"/api/v1/tool-items/{tool_item.id}",
        headers={"Authorization": f"Bearer {api_key_mill_plain}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == tool_item.id
    
    # Test 2: API key without matching tag gets denied
    api_key_lathe_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Lathe-1 Key",
        scopes=["read"],
        tags=["lathe-1"]
    )
    
    response = client.get(
        f"/api/v1/tool-items/{tool_item.id}",
        headers={"Authorization": f"Bearer {api_key_lathe_plain}"}
    )
    
    assert response.status_code == 403


@pytest.mark.integration
def test_update_tool_item_with_tag_enforcement(client, db_session):
    """Test updating tool items with tag-based access control."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create tool item with tags
    tool_item = ToolItem(
        type="cutting_tool",
        manufacturer="Sandvik",
        tags=["mill-3"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=1
    )
    db_session.add(tool_item)
    db_session.commit()
    
    # Create API key with mill-3 tag
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read", "write:items"],
        tags=["mill-3", "production"]
    )
    
    # Test 1: Update with allowed tags succeeds
    response = client.put(
        "/api/v1/tool-items",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "id": tool_item.id,
                "version": 1,
                "description": "Updated description",
                "tags": ["mill-3", "production"]
            }]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    assert data["results"][0]["tags"] == ["mill-3", "production"]
    
    # Test 2: Update with unauthorized tags fails
    db_session.refresh(tool_item)
    response = client.put(
        "/api/v1/tool-items",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "id": tool_item.id,
                "version": 2,
                "tags": ["lathe-1"]
            }]
        }
    )
    
    assert response.status_code == 200  # Partial success
    data = response.json()
    assert data["success_count"] == 0
    assert data["error_count"] == 1
    assert "not authorized" in data["errors"][0]["message"].lower()


@pytest.mark.integration
def test_delete_tool_item_with_tag_enforcement(client, db_session):
    """Test deleting tool items with tag-based access control."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create tool items with different tags
    item_mill = ToolItem(
        type="cutting_tool",
        manufacturer="Sandvik",
        tags=["mill-3"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    item_lathe = ToolItem(
        type="holder",
        manufacturer="Haas",
        tags=["lathe-1"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add_all([item_mill, item_lathe])
    db_session.commit()
    
    # Create API key with mill-3 tag
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read", "write:items", "delete:items"],
        tags=["mill-3"]
    )
    
    # Test 1: Delete tool item with matching tag succeeds
    response = client.request(
        "DELETE",
        "/api/v1/tool-items",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={"ids": [item_mill.id]}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    
    # Test 2: Delete tool item without matching tag fails
    response = client.request(
        "DELETE",
        "/api/v1/tool-items",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={"ids": [item_lathe.id]}
    )
    
    assert response.status_code == 200  # Partial success
    data = response.json()
    assert data["success_count"] == 0
    assert data["error_count"] == 1
    assert "not authorized" in data["errors"][0]["message"].lower()


@pytest.mark.integration
def test_session_auth_bypasses_tag_checks_tool_items(client, db_session):
    """Test that session authentication bypasses tag checks for tool items."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    db_session.commit()
    
    # Create tool item with any tags via session auth
    response = client.post(
        "/api/v1/tool-items",
        cookies={"session": session_id},
        json={
            "items": [{
                "type": "cutting_tool",
                "manufacturer": "Sandvik",
                "tags": ["mill-3", "lathe-1", "production", "custom-tag"]
            }]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    assert len(data["results"][0]["tags"]) == 4
