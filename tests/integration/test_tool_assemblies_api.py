# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for ToolAssembly bulk API endpoints.

Tests bulk-first design: all operations accept arrays.

Assumptions:
- POST /api/v1/tool-assemblies - Create (bulk)
- GET /api/v1/tool-assemblies - List/query with filters
- PUT /api/v1/tool-assemblies - Update (bulk) with version checking
- DELETE /api/v1/tool-assemblies - Delete (bulk)
- components is JSON array of {item_id, role, position, gauge_offset}
- Multi-tenant: Users only access their own data
"""
import pytest
from datetime import datetime, UTC
from loobric_server.api.auth import get_session_user


@pytest.mark.integration
def test_bulk_create_tool_assemblies(client, db_session):
    """Test bulk create of tool assemblies.
    
    Assumptions:
    - Accepts array of assemblies
    - components is array of tool item references
    - Returns success count and per-item results
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    assemblies = [
        {
            "name": "10mm End Mill Assembly",
            "description": "Complete cutting tool with holder",
            "components": [
                {"item_id": "tool-1", "role": "cutter", "position": 0},
                {"item_id": "holder-1", "role": "holder", "position": 1}
            ]
        },
        {
            "name": "Drill Assembly",
            "description": "HSS drill with ER collet",
            "components": [
                {"item_id": "drill-1", "role": "cutter", "position": 0}
            ]
        }
    ]
    
    client.cookies.set("session", session_id)
    
    response = client.post(
        "/api/v1/tool-assemblies",
        json={"items": assemblies}
    )
    
    assert response.status_code == 201  # 201 Created is the correct status code for successful resource creation
    data = response.json()
    
    assert data["success_count"] == 2
    assert len(data["results"]) == 2
    assert data["error_count"] == 0
    
    # Verify components stored correctly
    assert data["results"][0]["components"] == assemblies[0]["components"]


@pytest.mark.integration
def test_create_validates_required_fields(client, db_session):
    """Test validation of required fields.
    
    Assumptions:
    - name and components are required
    - Returns error for invalid items
    - Partial success supported
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    assemblies = [
        {
            "name": "Valid Assembly",
            "components": [{"item_id": "tool-1", "role": "cutter"}]
        },
        {
            # Missing required 'name' field
            "components": [{"item_id": "tool-2", "role": "cutter"}]
        }
    ]
    
    client.cookies.set("session", session_id)
    
    response = client.post(
        "/api/v1/tool-assemblies",
        json={"items": assemblies}
    )
    
    # Should return 422 Unprocessable Entity due to validation error
    assert response.status_code == 422
    data = response.json()
    
    # Check that we got a validation error for the missing name field
    assert "field required" in data["detail"][0]["msg"].lower()


@pytest.mark.integration
def test_bulk_read_tool_assemblies(client, db_session):
    """Test bulk read/list of tool assemblies.
    
    Assumptions:
    - GET returns array of assemblies
    - Filters by user_id automatically
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create some assemblies
    for i in range(3):
        assembly = ToolAssembly(
            name=f"Assembly {i}",
            components=[{"item_id": f"tool-{i}", "role": "cutter"}],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
        db_session.add(assembly)
    db_session.commit()
    
    client.cookies.set("session", session_id)
    
    response = client.get("/api/v1/tool-assemblies")
    
    assert response.status_code == 200  # 200 OK for successful GET requests
    data = response.json()
    
    assert "items" in data
    assert len(data["items"]) == 3
    assert data["total"] == 3


@pytest.mark.integration
def test_read_filters_by_user(client, db_session):
    """Test that users only see their own tool assemblies.
    
    Assumptions:
    - Multi-tenant isolation
    - User A cannot see User B's assemblies
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly
    
    # Create test users
    user1 = create_user(db_session, "user1@example.com", "Password123")
    user2 = create_user(db_session, "user2@example.com", "Password123")
    db_session.commit()
    db_session.refresh(user1)
    db_session.refresh(user2)
    
    print(f"[DEBUG] Created user1: {user1.id} (type: {type(user1.id)})")
    print(f"[DEBUG] Created user2: {user2.id} (type: {type(user2.id)})")
    
    # Create assemblies for each user
    for user in [user1, user2]:
        assembly = ToolAssembly(
            name=f"Assembly for {user.email}",
            components=[{"item_id": "tool-1", "role": "cutter"}],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
        db_session.add(assembly)
    db_session.commit()
    
    # Verify assemblies were created with correct user_ids
    all_assemblies = db_session.query(ToolAssembly).all()
    print(f"[DEBUG] All assemblies after creation: {len(all_assemblies)}")
    for a in all_assemblies:
        print(f"  - ID: {a.id}, User ID: {a.user_id} (type: {type(a.user_id)}), Name: {a.name}")
    
    # Create session for user1
    session1 = create_session(user1.id)
    
    # Make the request with the session cookie
    response = client.get(
        "/api/v1/tool-assemblies",
        cookies={"session": session1}
    )
    
    # Debug information
    print("\n[DEBUG] Test Setup:")
    print(f"- User1 ID: {user1.id} (type: {type(user1.id)})")
    print(f"- User2 ID: {user2.id}")
    print(f"- Session token: {session1}")
    
    # Verify session lookup
    session_user = get_session_user(session1, db_session)
    print(f"- Session user ID: {session_user.id if session_user else 'None'}")
    
    print("\n[DEBUG] Database State:")
    for a in db_session.query(ToolAssembly).all():
        print(f"  - ID: {a.id}, User ID: {a.user_id} (type: {type(a.user_id)}), Name: {a.name}")
    
    print("\n[DEBUG] Response:")
    print(f"- Status: {response.status_code}")
    print(f"- Content: {response.text}")
    
    # Verify the response
    assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}"
    data = response.json()
    
    # Debug: Print the actual user_id from the first assembly (if any)
    if data["items"]:
        print(f"[DEBUG] First assembly user_id: {data['items'][0]['user_id']} (type: {type(data['items'][0]['user_id'])})")
    
    # Check that we only get user1's assembly
    assert len(data["items"]) == 1, f"Expected 1 assembly, got {len(data['items'])}"
    assert str(data["items"][0]["user_id"]) == str(user1.id), f"Expected user_id {user1.id}, got {data['items'][0]['user_id']}"


@pytest.mark.integration
def test_bulk_update_tool_assemblies(client, db_session):
    """Test bulk update with version checking.
    
    Assumptions:
    - Updates version field
    - Checks version for conflicts
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create assemblies
    assembly1 = ToolAssembly(
        name="Assembly 1",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=1
    )
    assembly2 = ToolAssembly(
        name="Assembly 2",
        components=[{"item_id": "tool-2", "role": "cutter"}],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=1
    )
    db_session.add_all([assembly1, assembly2])
    db_session.commit()
    
    # Update both
    updates = [
        {
            "id": assembly1.id,
            "version": 1,
            "description": "Updated description 1"
        },
        {
            "id": assembly2.id,
            "version": 1,
            "description": "Updated description 2"
        }
    ]
    
    client.cookies.set("session", session_id)
    
    response = client.put(
        "/api/v1/tool-assemblies",
        json={"items": updates}
    )
    
    assert response.status_code == 200  # 200 OK for successful PUT requests
    data = response.json()
    
    assert data["success_count"] == 2
    assert data["error_count"] == 0
    
    # Verify version incremented
    for result in data["results"]:
        assert result["version"] == 2


@pytest.mark.integration
def test_update_detects_version_conflict(client, db_session):
    """Test version conflict detection.
    
    Assumptions:
    - Update with wrong version fails
    - Returns error with conflict details
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create assembly
    assembly = ToolAssembly(
        name="Test Assembly",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=2
    )
    db_session.add(assembly)
    db_session.commit()
    
    # Try to update with old version
    client.cookies.set("session", session_id)
    
    response = client.put(
        "/api/v1/tool-assemblies",
        json={
            "items": [{
                "id": assembly.id,
                "version": 1,  # Wrong version
                "description": "Updated"
            }]
        }
    )
    
    assert response.status_code == 409  # 409 Conflict for version conflicts
    data = response.json()
    
    assert data["success_count"] == 0
    assert data["error_count"] == 1
    assert "version" in data["errors"][0]["message"].lower() or "conflict" in data["errors"][0]["message"].lower()


@pytest.mark.integration
def test_bulk_delete_tool_assemblies(client, db_session):
    """Test bulk delete of assemblies.
    
    Assumptions:
    - DELETE accepts array of IDs
    - Returns success count
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create assemblies
    assemblies = []
    for i in range(3):
        assembly = ToolAssembly(
            name=f"Assembly {i}",
            components=[{"item_id": f"tool-{i}", "role": "cutter"}],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
        assemblies.append(assembly)
        db_session.add(assembly)
    db_session.commit()
    
    # Delete first two
    client.cookies.set("session", session_id)
    
    response = client.request(
        "DELETE",
        "/api/v1/tool-assemblies",
        json={"ids": [assemblies[0].id, assemblies[1].id]}
    )
    
    assert response.status_code == 200  # 200 OK for successful DELETE requests
    data = response.json()
    
    assert data["success_count"] == 2
    assert data["error_count"] == 0
    
    # Verify deletion
    remaining = db_session.query(ToolAssembly).filter(ToolAssembly.user_id == user.id).all()
    assert len(remaining) == 1


@pytest.mark.integration
def test_pagination(client, db_session):
    """Test pagination of results.
    
    Assumptions:
    - Supports limit and offset
    - Returns total count
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create 15 assemblies
    for i in range(15):
        assembly = ToolAssembly(
            name=f"Assembly {i}",
            components=[{"item_id": f"tool-{i}", "role": "cutter"}],
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
        db_session.add(assembly)
    db_session.commit()
    
    # Get first page
    client.cookies.set("session", session_id)
    
    response = client.get("/api/v1/tool-assemblies?limit=10&offset=0")
    
    assert response.status_code == 200  # 200 OK for successful GET requests
    data = response.json()
    
    assert len(data["items"]) == 10
    assert data["total"] == 15
    assert data["limit"] == 10
    assert data["offset"] == 0


@pytest.mark.integration
def test_get_single_tool_assembly_success(client, db_session):
    """Test retrieving a single tool assembly by ID."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly

    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)

    assembly = ToolAssembly(
        name="Assembly X",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(assembly)
    db_session.commit()

    response = client.get(
        f"/api/v1/tool-assemblies/{assembly.id}",
        cookies={"session": session_id}
    )
    assert response.status_code == 200  # 200 OK for successful GET requests
    data = response.json()
    assert data["id"] == assembly.id
    assert data["name"] == "Assembly X"


@pytest.mark.integration
def test_get_single_tool_assembly_not_found_other_user(client, db_session):
    """Test retrieving another user's tool assembly returns 404."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly

    owner = create_user(db_session, "owner@example.com", "Password123")
    other = create_user(db_session, "other@example.com", "Password123")
    session_id = create_session(other.id)

    assembly = ToolAssembly(
        name="Owner Assembly",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        user_id=owner.id,
        created_by=owner.id,
        updated_by=owner.id
    )
    db_session.add(assembly)
    db_session.commit()

    response = client.get(
        f"/api/v1/tool-assemblies/{assembly.id}",
        cookies={"session": session_id}
    )
    assert response.status_code == 404
