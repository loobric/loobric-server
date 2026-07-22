# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for tag-based access control on tool presets.

Tests tag enforcement across CRUD operations for tool presets.

Assumptions:
- API keys can have tags that restrict access to resources
- Resources (tool presets) can have tags
- Access granted if any API key tag matches any resource tag
- Empty API key tags = no restrictions (access all resources with proper scopes)
- Empty resource tags = accessible to all keys with proper scopes
- Admin scope (admin:*) bypasses tag checks
- Session auth bypasses tag checks (user owns all their resources)
"""
import pytest
from loobric_server.database.schema import ToolPreset


@pytest.mark.integration
def test_create_tool_preset_with_api_key_tags(client, db_session):
    """Test creating tool presets with API key that has tags."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create API key with tags
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read", "write:presets"],
        tags=["mill-3", "production"]
    )
    
    # Test 1: Create tool preset with allowed tags
    response = client.post(
        "/api/v1/tool-presets",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "machine_id": "mill-3",
                "tool_number": 1,
                "description": "Mill tool preset",
                "tags": ["mill-3"]
            }]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    assert data["results"][0]["tags"] == ["mill-3"]
    
    # Test 2: Create tool preset with unauthorized tag fails
    response = client.post(
        "/api/v1/tool-presets",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "machine_id": "lathe-1",
                "tool_number": 2,
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
def test_list_tool_presets_filtered_by_api_key_tags(client, db_session):
    """Test listing tool presets is filtered by API key tags."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create tool presets with different tags
    tool_presets = [
        ToolPreset(
            machine_id="mill-3",
            tool_number=1,
            tags=["mill-3", "production"],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        ),
        ToolPreset(
            machine_id="lathe-1",
            tool_number=2,
            tags=["lathe-1"],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        ),
        ToolPreset(
            machine_id="mill-3",
            tool_number=3,
            tags=["production"],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        ),
    ]
    for preset in tool_presets:
        db_session.add(preset)
    db_session.commit()
    
    # Create API key with mill-3 tag
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read"],
        tags=["mill-3"]
    )
    
    # List tool presets with tagged API key
    response = client.get(
        "/api/v1/tool-presets",
        headers={"Authorization": f"Bearer {api_key_plain}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Should only see tool presets with mill-3 tag
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["machine_id"] == "mill-3"
    assert data["items"][0]["tool_number"] == 1


@pytest.mark.integration
def test_get_tool_preset_with_tag_access(client, db_session):
    """Test getting single tool preset with tag-based access control."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create tool preset with tags
    tool_preset = ToolPreset(
        machine_id="mill-3",
        tool_number=1,
        tags=["mill-3", "production"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(tool_preset)
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
        f"/api/v1/tool-presets/{tool_preset.id}",
        headers={"Authorization": f"Bearer {api_key_mill_plain}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == tool_preset.id
    
    # Test 2: API key without matching tag gets denied
    api_key_lathe_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Lathe-1 Key",
        scopes=["read"],
        tags=["lathe-1"]
    )
    
    response = client.get(
        f"/api/v1/tool-presets/{tool_preset.id}",
        headers={"Authorization": f"Bearer {api_key_lathe_plain}"}
    )
    
    assert response.status_code == 403


@pytest.mark.integration
def test_update_tool_preset_with_tag_enforcement(client, db_session):
    """Test updating tool presets with tag-based access control."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create tool preset with tags
    tool_preset = ToolPreset(
        machine_id="mill-3",
        tool_number=1,
        tags=["mill-3"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=1
    )
    db_session.add(tool_preset)
    db_session.commit()
    
    # Create API key with mill-3 tag
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read", "write:presets"],
        tags=["mill-3", "production"]
    )
    
    # Test 1: Update with allowed tags succeeds
    response = client.put(
        "/api/v1/tool-presets",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "id": tool_preset.id,
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
    db_session.refresh(tool_preset)
    response = client.put(
        "/api/v1/tool-presets",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "id": tool_preset.id,
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
def test_delete_tool_preset_with_tag_enforcement(client, db_session):
    """Test deleting tool presets with tag-based access control."""
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create tool presets with different tags
    preset_mill = ToolPreset(
        machine_id="mill-3",
        tool_number=1,
        tags=["mill-3"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    preset_lathe = ToolPreset(
        machine_id="lathe-1",
        tool_number=2,
        tags=["lathe-1"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add_all([preset_mill, preset_lathe])
    db_session.commit()
    
    # Create API key with mill-3 tag
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read", "write:presets", "delete:presets"],
        tags=["mill-3"]
    )
    
    # Test 1: Delete tool preset with matching tag succeeds
    response = client.request(
        "DELETE",
        "/api/v1/tool-presets",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={"ids": [preset_mill.id]}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    
    # Test 2: Delete tool preset without matching tag fails
    response = client.request(
        "DELETE",
        "/api/v1/tool-presets",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={"ids": [preset_lathe.id]}
    )
    
    assert response.status_code == 200  # Partial success
    data = response.json()
    assert data["success_count"] == 0
    assert data["error_count"] == 1
    assert "not authorized" in data["errors"][0]["message"].lower()


@pytest.mark.integration
def test_session_auth_bypasses_tag_checks_tool_presets(client, db_session):
    """Test that session authentication bypasses tag checks for tool presets."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    db_session.commit()
    
    # Create tool preset with any tags via session auth
    response = client.post(
        "/api/v1/tool-presets",
        cookies={"session": session_id},
        json={
            "items": [{
                "machine_id": "mill-3",
                "tool_number": 1,
                "tags": ["mill-3", "lathe-1", "production", "custom-tag"]
            }]
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    assert len(data["results"][0]["tags"]) == 4
