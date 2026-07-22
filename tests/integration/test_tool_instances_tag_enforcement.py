# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for tag-based access control on tool instances.

Tests tag enforcement across CRUD operations for tool instances.

Assumptions:
- API keys can have tags that restrict access to resources
- Resources (tool instances) can have tags
- Access granted if any API key tag matches any resource tag
- Empty API key tags = no restrictions (access all resources with proper scopes)
- Empty resource tags = accessible to all keys with proper scopes
- Admin scope (admin:*) bypasses tag checks
- Session auth bypasses tag checks (user owns all their resources)
"""
import pytest
from loobric_server.database.schema import ToolInstance


@pytest.mark.integration
def test_create_tool_instance_with_api_key_tags(client, db_session):
    """Test creating tool instances with API key that has tags."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create API key with tags
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read", "write:instances"],
        tags=["mill-3", "production"]
    )
    
    # Test 1: Create tool instance with allowed tags
    response = client.post(
        "/api/v1/tool-instances",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "assembly_id": "asm-123",
                "serial_number": "SN-001",
                "status": "available",
                "tags": ["mill-3"]
            }]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    assert data["results"][0]["tags"] == ["mill-3"]
    
    # Test 2: Create tool instance with unauthorized tag fails
    response = client.post(
        "/api/v1/tool-instances",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "assembly_id": "asm-456",
                "serial_number": "SN-002",
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
def test_list_tool_instances_filtered_by_api_key_tags(client, db_session):
    """Test listing tool instances is filtered by API key tags."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create tool instances with different tags
    tool_instances = [
        ToolInstance(
            assembly_id="asm-123",
            serial_number="SN-001",
            status="available",
            tags=["mill-3", "production"],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        ),
        ToolInstance(
            assembly_id="asm-456",
            serial_number="SN-002",
            status="available",
            tags=["lathe-1"],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        ),
        ToolInstance(
            assembly_id="asm-789",
            serial_number="SN-003",
            status="in_use",
            tags=["production"],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        ),
    ]
    for instance in tool_instances:
        db_session.add(instance)
    db_session.commit()
    
    # Create API key with mill-3 tag
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read"],
        tags=["mill-3"]
    )
    
    # List tool instances with tagged API key
    response = client.get(
        "/api/v1/tool-instances",
        headers={"Authorization": f"Bearer {api_key_plain}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Should only see tool instances with mill-3 tag
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["serial_number"] == "SN-001"


@pytest.mark.integration
def test_get_tool_instance_with_tag_access(client, db_session):
    """Test getting single tool instance with tag-based access control."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create tool instance with tags
    tool_instance = ToolInstance(
        assembly_id="asm-123",
        serial_number="SN-001",
        status="available",
        tags=["mill-3", "production"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(tool_instance)
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
        f"/api/v1/tool-instances/{tool_instance.id}",
        headers={"Authorization": f"Bearer {api_key_mill_plain}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == tool_instance.id
    
    # Test 2: API key without matching tag gets denied
    api_key_lathe_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Lathe-1 Key",
        scopes=["read"],
        tags=["lathe-1"]
    )
    
    response = client.get(
        f"/api/v1/tool-instances/{tool_instance.id}",
        headers={"Authorization": f"Bearer {api_key_lathe_plain}"}
    )
    
    assert response.status_code == 403


@pytest.mark.integration
def test_update_tool_instance_with_tag_enforcement(client, db_session):
    """Test updating tool instances with tag-based access control."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create tool instance with tags
    tool_instance = ToolInstance(
        assembly_id="asm-123",
        serial_number="SN-001",
        status="available",
        tags=["mill-3"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=1
    )
    db_session.add(tool_instance)
    db_session.commit()
    
    # Create API key with mill-3 tag
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read", "write:instances"],
        tags=["mill-3", "production"]
    )
    
    # Test 1: Update with allowed tags succeeds
    response = client.put(
        "/api/v1/tool-instances",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "id": tool_instance.id,
                "version": 1,
                "status": "in_use",
                "tags": ["mill-3", "production"]
            }]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    assert data["results"][0]["tags"] == ["mill-3", "production"]
    
    # Test 2: Update with unauthorized tags fails
    db_session.refresh(tool_instance)
    response = client.put(
        "/api/v1/tool-instances",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "id": tool_instance.id,
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
def test_delete_tool_instance_with_tag_enforcement(client, db_session):
    """Test deleting tool instances with tag-based access control."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create tool instances with different tags
    instance_mill = ToolInstance(
        assembly_id="asm-123",
        serial_number="SN-001",
        status="available",
        tags=["mill-3"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    instance_lathe = ToolInstance(
        assembly_id="asm-456",
        serial_number="SN-002",
        status="available",
        tags=["lathe-1"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add_all([instance_mill, instance_lathe])
    db_session.commit()
    
    # Create API key with mill-3 tag
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read", "write:instances", "delete:instances"],
        tags=["mill-3"]
    )
    
    # Test 1: Delete tool instance with matching tag succeeds
    response = client.request(
        "DELETE",
        "/api/v1/tool-instances",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={"ids": [instance_mill.id]}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    
    # Test 2: Delete tool instance without matching tag fails
    response = client.request(
        "DELETE",
        "/api/v1/tool-instances",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={"ids": [instance_lathe.id]}
    )
    
    assert response.status_code == 200  # Partial success
    data = response.json()
    assert data["success_count"] == 0
    assert data["error_count"] == 1
    assert "not authorized" in data["errors"][0]["message"].lower()


@pytest.mark.integration
def test_session_auth_bypasses_tag_checks_tool_instances(client, db_session):
    """Test that session authentication bypasses tag checks for tool instances."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    db_session.commit()
    
    # Create tool instance with any tags via session auth
    response = client.post(
        "/api/v1/tool-instances",
        cookies={"session": session_id},
        json={
            "items": [{
                "assembly_id": "asm-123",
                "serial_number": "SN-001",
                "tags": ["mill-3", "lathe-1", "production", "custom-tag"]
            }]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    assert len(data["results"][0]["tags"]) == 4
