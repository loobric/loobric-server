# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for ToolPreset bulk API endpoints.

Tests bulk-first design: all operations accept arrays.

Assumptions:
- POST /api/v1/tool-presets - Create (bulk)
- GET /api/v1/tool-presets - List/query with filters
- PUT /api/v1/tool-presets - Update (bulk) with version checking
- DELETE /api/v1/tool-presets - Delete (bulk)
- instance_id references ToolInstance
- machine_id and tool_number identify preset on machine
- Multi-tenant: Users only access their own data
"""
import pytest
from datetime import datetime, UTC


@pytest.mark.integration
def test_bulk_create_tool_presets(client, db_session):
    """Test bulk create of tool presets.
    
    Assumptions:
    - Accepts array of presets
    - machine_id, tool_number, instance_id required
    - offsets, orientation stored as JSON
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly, ToolInstance
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create assembly and instance
    assembly = ToolAssembly(
        name="Test Assembly",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(assembly)
    db_session.commit()
    
    instance = ToolInstance(
        assembly_id=assembly.id,
        serial_number="SN-001",
        status="available",
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(instance)
    db_session.commit()
    
    presets = [
        {
            "machine_id": "HAAS-VF2",
            "tool_number": 1,
            "instance_id": instance.id,
            "pocket": 1,
            "offsets": {"length": 150.5, "diameter": 10.0}
        },
        {
            "machine_id": "HAAS-VF2",
            "tool_number": 2,
            "instance_id": instance.id,
            "pocket": 2,
            "offsets": {"length": 75.0, "diameter": 6.0}
        }
    ]
    
    client.cookies.set("session", session_id)
    
    response = client.post(
        "/api/v1/tool-presets",
        json={"items": presets}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 2
    assert len(data["results"]) == 2
    assert data["error_count"] == 0
    
    # Verify data stored correctly
    assert data["results"][0]["machine_id"] == "HAAS-VF2"
    assert data["results"][0]["tool_number"] == 1


@pytest.mark.integration
def test_create_validates_required_fields(client, db_session):
    """Test validation of required fields.
    
    Assumptions:
    - machine_id, tool_number, instance_id required
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly, ToolInstance
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create assembly and instance
    assembly = ToolAssembly(
        name="Test Assembly",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(assembly)
    db_session.commit()
    
    instance = ToolInstance(
        assembly_id=assembly.id,
        serial_number="SN-001",
        status="available",
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(instance)
    db_session.commit()
    
    presets = [
        {
            "machine_id": "HAAS-VF2",
            "tool_number": 1,
            "instance_id": instance.id
        },
        {
            # Missing required 'machine_id'
            "tool_number": 2,
            "instance_id": instance.id
        }
    ]
    
    client.cookies.set("session", session_id)
    
    response = client.post(
        "/api/v1/tool-presets",
        json={"items": presets}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 1
    assert data["error_count"] == 1


@pytest.mark.integration
def test_bulk_read_tool_presets(client, db_session):
    """Test bulk read/list of tool presets."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly, ToolInstance, ToolPreset
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create assembly and instance
    assembly = ToolAssembly(
        name="Test Assembly",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(assembly)
    db_session.commit()
    
    instance = ToolInstance(
        assembly_id=assembly.id,
        serial_number="SN-001",
        status="available",
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(instance)
    db_session.commit()
    
    # Create presets
    for i in range(3):
        preset = ToolPreset(
            machine_id="HAAS-VF2",
            tool_number=i + 1,
            instance_id=instance.id,
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
        db_session.add(preset)
    db_session.commit()
    
    client.cookies.set("session", session_id)
    
    response = client.get("/api/v1/tool-presets")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "items" in data
    assert len(data["items"]) == 3


@pytest.mark.integration
def test_filter_by_machine(client, db_session):
    """Test filtering presets by machine_id."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly, ToolInstance, ToolPreset
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create assembly and instance
    assembly = ToolAssembly(
        name="Test Assembly",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(assembly)
    db_session.commit()
    
    instance = ToolInstance(
        assembly_id=assembly.id,
        serial_number="SN-001",
        status="available",
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(instance)
    db_session.commit()
    
    # Create presets for different machines
    machines = ["HAAS-VF2", "DMG-MORI", "HAAS-VF2"]
    for i, machine in enumerate(machines):
        preset = ToolPreset(
            machine_id=machine,
            tool_number=i + 1,
            instance_id=instance.id,
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
        db_session.add(preset)
    db_session.commit()
    
    client.cookies.set("session", session_id)
    
    response = client.get("/api/v1/tool-presets?machine_id=HAAS-VF2")
    
    assert response.status_code == 200
    data = response.json()
    
    assert len(data["items"]) == 2
    for item in data["items"]:
        assert item["machine_id"] == "HAAS-VF2"


@pytest.mark.integration
def test_bulk_update_tool_presets(client, db_session):
    """Test bulk update with version checking."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly, ToolInstance, ToolPreset
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create assembly and instance
    assembly = ToolAssembly(
        name="Test Assembly",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(assembly)
    db_session.commit()
    
    instance = ToolInstance(
        assembly_id=assembly.id,
        serial_number="SN-001",
        status="available",
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(instance)
    db_session.commit()
    
    # Create presets
    preset1 = ToolPreset(
        machine_id="HAAS-VF2",
        tool_number=1,
        instance_id=instance.id,
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=1
    )
    preset2 = ToolPreset(
        machine_id="HAAS-VF2",
        tool_number=2,
        instance_id=instance.id,
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=1
    )
    db_session.add_all([preset1, preset2])
    db_session.commit()
    
    # Update both
    updates = [
        {
            "id": preset1.id,
            "version": 1,
            "offsets": {"length": 155.0, "diameter": 10.0}
        },
        {
            "id": preset2.id,
            "version": 1,
            "pocket": 5
        }
    ]
    
    client.cookies.set("session", session_id)
    
    response = client.put(
        "/api/v1/tool-presets",
        json={"items": updates}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 2
    assert data["error_count"] == 0


@pytest.mark.integration
def test_get_single_tool_preset_success(client, db_session):
    """Test retrieving a single tool preset by ID."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly, ToolInstance, ToolPreset

    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)

    # Create assembly and instance
    assembly = ToolAssembly(
        name="Asm",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(assembly)
    db_session.commit()

    instance = ToolInstance(
        assembly_id=assembly.id,
        serial_number="SN-001",
        status="available",
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(instance)
    db_session.commit()

    preset = ToolPreset(
        machine_id="HAAS-VF2",
        tool_number=1,
        instance_id=instance.id,
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(preset)
    db_session.commit()

    response = client.get(
        f"/api/v1/tool-presets/{preset.id}",
        cookies={"session": session_id}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == preset.id
    assert data["machine_id"] == "HAAS-VF2"


@pytest.mark.integration
def test_get_single_tool_preset_not_found_other_user(client, db_session):
    """Test retrieving another user's tool preset returns 404."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly, ToolInstance, ToolPreset

    owner = create_user(db_session, "owner@example.com", "Password123")
    other = create_user(db_session, "other@example.com", "Password123")
    session_id = create_session(other.id)

    # Create assembly/instance under owner
    assembly = ToolAssembly(
        name="Asm",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        user_id=owner.id,
        created_by=owner.id,
        updated_by=owner.id
    )
    db_session.add(assembly)
    db_session.commit()

    instance = ToolInstance(
        assembly_id=assembly.id,
        serial_number="SN-001",
        status="available",
        user_id=owner.id,
        created_by=owner.id,
        updated_by=owner.id
    )
    db_session.add(instance)
    db_session.commit()

    preset = ToolPreset(
        machine_id="HAAS-VF2",
        tool_number=1,
        instance_id=instance.id,
        user_id=owner.id,
        created_by=owner.id,
        updated_by=owner.id
    )
    db_session.add(preset)
    db_session.commit()

    response = client.get(
        f"/api/v1/tool-presets/{preset.id}",
        cookies={"session": session_id}
    )
    assert response.status_code == 404


@pytest.mark.integration
def test_bulk_delete_tool_presets(client, db_session):
    """Test bulk delete of presets."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly, ToolInstance, ToolPreset
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create assembly and instance
    assembly = ToolAssembly(
        name="Test Assembly",
        components=[{"item_id": "tool-1", "role": "cutter"}],
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(assembly)
    db_session.commit()
    
    instance = ToolInstance(
        assembly_id=assembly.id,
        serial_number="SN-001",
        status="available",
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(instance)
    db_session.commit()
    
    # Create presets
    presets = []
    for i in range(3):
        preset = ToolPreset(
            machine_id="HAAS-VF2",
            tool_number=i + 1,
            instance_id=instance.id,
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
        presets.append(preset)
        db_session.add(preset)
    db_session.commit()
    
    # Delete first two
    client.cookies.set("session", session_id)
    
    response = client.request(
        "DELETE",
        "/api/v1/tool-presets",
        json={"ids": [presets[0].id, presets[1].id]}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 2
    assert data["error_count"] == 0
