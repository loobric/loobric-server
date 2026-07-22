# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for tag-based access control enforcement.

Tests tag enforcement across CRUD operations for tool assemblies.

Assumptions:
- API keys can have tags that restrict access to resources
- Resources (assemblies, items, presets, etc.) can have tags
- Access granted if any API key tag matches any resource tag
- Empty API key tags = no restrictions (access all resources with proper scopes)
- Empty resource tags = accessible to all keys with proper scopes
- Admin scope (admin:*) bypasses tag checks
- Session auth bypasses tag checks (user owns all their resources)
"""
import pytest
from loobric_server.database.schema import ToolAssembly


@pytest.mark.integration
def test_create_assembly_with_api_key_tags(client, db_session):
    """Test creating assemblies with API key that has tags.
    
    Assumptions:
    - API key with tags can only create resources with those tags
    - Creating resource with unauthorized tags returns error
    - Creating resource with subset of key tags succeeds
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create API key with tags
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read", "write:assemblies"],
        tags=["mill-3", "production"]
    )
    
    # Test 1: Create assembly with allowed tags
    response = client.post(
        "/api/v1/tool-assemblies",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "name": "Mill-3 Assembly",
                "components": [{"item_id": "tool-1", "role": "cutter"}],
                "tags": ["mill-3"]
            }]
        }
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["success_count"] == 1
    assert data["results"][0]["tags"] == ["mill-3"]
    
    # Test 2: Create assembly with multiple allowed tags
    response = client.post(
        "/api/v1/tool-assemblies",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "name": "Production Assembly",
                "components": [{"item_id": "tool-2", "role": "cutter"}],
                "tags": ["mill-3", "production"]
            }]
        }
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["success_count"] == 1
    
    # Test 3: Create assembly with unauthorized tag fails
    response = client.post(
        "/api/v1/tool-assemblies",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "name": "Lathe Assembly",
                "components": [{"item_id": "tool-3", "role": "cutter"}],
                "tags": ["lathe-1"]
            }]
        }
    )
    
    assert response.status_code == 201  # Partial success response
    data = response.json()
    assert data["success_count"] == 0
    assert data["error_count"] == 1
    assert "not authorized" in data["errors"][0]["message"].lower()


@pytest.mark.integration
def test_list_assemblies_filtered_by_api_key_tags(client, db_session):
    """Test listing assemblies is filtered by API key tags.
    
    Assumptions:
    - API key with tags only sees resources with matching tags
    - API key without tags sees all resources (with proper scopes)
    - Returns only assemblies where at least one tag matches
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create assemblies with different tags
    assemblies = [
        ToolAssembly(
            name="Mill-3 Assembly",
            components=[{"item_id": "tool-1", "role": "cutter"}],
            tags=["mill-3", "production"],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        ),
        ToolAssembly(
            name="Lathe-1 Assembly",
            components=[{"item_id": "tool-2", "role": "cutter"}],
            tags=["lathe-1"],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        ),
        ToolAssembly(
            name="Production Assembly",
            components=[{"item_id": "tool-3", "role": "cutter"}],
            tags=["production"],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        ),
        ToolAssembly(
            name="Untagged Assembly",
            components=[{"item_id": "tool-4", "role": "cutter"}],
            tags=[],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
    ]
    for a in assemblies:
        db_session.add(a)
    db_session.commit()
    
    # Create API key with mill-3 tag
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read"],
        tags=["mill-3"]
    )
    
    # List assemblies with tagged API key
    response = client.get(
        "/api/v1/tool-assemblies",
        headers={"Authorization": f"Bearer {api_key_plain}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Should only see assemblies with mill-3 tag
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "Mill-3 Assembly"


@pytest.mark.integration
def test_get_assembly_with_tag_access(client, db_session):
    """Test getting single assembly with tag-based access control.
    
    Assumptions:
    - API key with matching tags can access assembly
    - API key without matching tags gets 403
    - Resource owner can always access (session auth)
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create assembly with tags
    assembly = ToolAssembly(
        name="Mill-3 Assembly",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        tags=["mill-3", "production"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(assembly)
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
        f"/api/v1/tool-assemblies/{assembly.id}",
        headers={"Authorization": f"Bearer {api_key_mill_plain}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == assembly.id
    
    # Test 2: API key without matching tag gets denied
    api_key_lathe_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Lathe-1 Key",
        scopes=["read"],
        tags=["lathe-1"]
    )
    
    response = client.get(
        f"/api/v1/tool-assemblies/{assembly.id}",
        headers={"Authorization": f"Bearer {api_key_lathe_plain}"}
    )
    
    assert response.status_code == 403


@pytest.mark.integration
def test_update_assembly_with_tag_enforcement(client, db_session):
    """Test updating assemblies with tag-based access control.
    
    Assumptions:
    - API key must have access to existing assembly tags
    - API key must have access to new tags being applied
    - Cannot change tags to unauthorized values
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create assembly with tags
    assembly = ToolAssembly(
        name="Mill-3 Assembly",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        tags=["mill-3"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=1
    )
    db_session.add(assembly)
    db_session.commit()
    
    # Create API key with mill-3 tag
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read", "write:assemblies"],
        tags=["mill-3", "production"]
    )
    
    # Test 1: Update with allowed tags succeeds
    response = client.put(
        "/api/v1/tool-assemblies",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "id": assembly.id,
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
    db_session.refresh(assembly)
    response = client.put(
        "/api/v1/tool-assemblies",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={
            "items": [{
                "id": assembly.id,
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
def test_delete_assembly_with_tag_enforcement(client, db_session):
    """Test deleting assemblies with tag-based access control.
    
    Assumptions:
    - API key must have access to assembly tags to delete
    - API key without matching tags cannot delete
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create assemblies with different tags
    assembly_mill = ToolAssembly(
        name="Mill-3 Assembly",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        tags=["mill-3"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    assembly_lathe = ToolAssembly(
        name="Lathe-1 Assembly",
        components=[{"item_id": "tool-2", "role": "cutter"}],
        tags=["lathe-1"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add_all([assembly_mill, assembly_lathe])
    db_session.commit()
    
    # Create API key with mill-3 tag
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Mill-3 Key",
        scopes=["read", "write:assemblies", "delete:assemblies"],
        tags=["mill-3"]
    )
    
    # Test 1: Delete assembly with matching tag succeeds
    response = client.request(
        "DELETE",
        "/api/v1/tool-assemblies",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={"ids": [assembly_mill.id]}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    
    # Test 2: Delete assembly without matching tag fails
    response = client.request(
        "DELETE",
        "/api/v1/tool-assemblies",
        headers={"Authorization": f"Bearer {api_key_plain}"},
        json={"ids": [assembly_lathe.id]}
    )
    
    assert response.status_code == 200  # Partial success
    data = response.json()
    assert data["success_count"] == 0
    assert data["error_count"] == 1
    assert "not authorized" in data["errors"][0]["message"].lower()


@pytest.mark.integration
def test_api_key_without_tags_accesses_all(client, db_session):
    """Test that API key without tags can access all resources.
    
    Assumptions:
    - Empty API key tags = no tag restrictions
    - Can access resources with any tags (or no tags)
    - Still requires proper scopes
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "test@example.com", "Password123")
    db_session.commit()
    
    # Create assemblies with various tags
    assemblies = [
        ToolAssembly(
            name="Mill Assembly",
            components=[{"item_id": "tool-1", "role": "cutter"}],
            tags=["mill-3"],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        ),
        ToolAssembly(
            name="Lathe Assembly",
            components=[{"item_id": "tool-2", "role": "cutter"}],
            tags=["lathe-1"],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        ),
        ToolAssembly(
            name="Untagged Assembly",
            components=[{"item_id": "tool-3", "role": "cutter"}],
            tags=[],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
    ]
    for a in assemblies:
        db_session.add(a)
    db_session.commit()
    
    # Create API key without tags
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Unrestricted Key",
        scopes=["read"],
        tags=[]
    )
    
    # List all assemblies
    response = client.get(
        "/api/v1/tool-assemblies",
        headers={"Authorization": f"Bearer {api_key_plain}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Should see all assemblies
    assert data["total"] == 3
    assert len(data["items"]) == 3


@pytest.mark.integration
def test_admin_scope_bypasses_tag_checks(client, db_session):
    """Test that admin:* scope bypasses tag-based access control.
    
    Assumptions:
    - admin:* scope grants access to all resources regardless of tags
    - Useful for backup, monitoring, admin operations
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    
    user = create_user(db_session, "admin@example.com", "Password123")
    db_session.commit()
    
    # Create assembly with specific tags
    assembly = ToolAssembly(
        name="Mill-3 Assembly",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        tags=["mill-3", "production"],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(assembly)
    db_session.commit()
    
    # Create admin API key with different tags
    api_key_plain = create_api_key(
        db_session,
        user_id=user.id,
        name="Admin Key",
        scopes=["admin:*"],
        tags=["backup"]  # Different tags, but admin scope bypasses
    )
    
    # Should be able to access assembly despite tag mismatch
    response = client.get(
        f"/api/v1/tool-assemblies/{assembly.id}",
        headers={"Authorization": f"Bearer {api_key_plain}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == assembly.id


@pytest.mark.integration
def test_session_auth_bypasses_tag_checks(client, db_session):
    """Test that session authentication bypasses tag checks.
    
    Assumptions:
    - Users own all their resources
    - Session auth doesn't use tag filtering
    - Can create/update resources with any tags
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    db_session.commit()
    
    # Create assembly with any tags via session auth
    response = client.post(
        "/api/v1/tool-assemblies",
        cookies={"session": session_id},
        json={
            "items": [{
                "name": "My Assembly",
                "components": [{"item_id": "tool-1", "role": "cutter"}],
                "tags": ["mill-3", "lathe-1", "production", "custom-tag"]
            }]
        }
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["success_count"] == 1
    assert len(data["results"][0]["tags"]) == 4
