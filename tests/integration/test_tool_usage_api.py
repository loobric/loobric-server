# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for ToolUsage bulk API endpoints.

Tests bulk-first design: all operations accept arrays.

Assumptions:
- POST /api/v1/tool-usage - Create (bulk)
- GET /api/v1/tool-usage - List/query with filters
- PUT /api/v1/tool-usage - Update (bulk) with version checking
- DELETE /api/v1/tool-usage - Delete (bulk)
- preset_id references ToolPreset
- Tracks runtime, cycle count, wear progression
- Multi-tenant: Users only access their own data
"""
import pytest
from datetime import datetime, UTC


@pytest.mark.integration
def test_bulk_create_tool_usage(client, db_session):
    """Test bulk create of tool usage records.
    
    Assumptions:
    - Accepts array of usage records
    - preset_id and start_time required
    - wear_progression and events stored as JSON arrays
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly, ToolInstance, ToolPreset
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create assembly, instance, and preset
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
    
    now = datetime.now(UTC)
    usage_records = [
        {
            "preset_id": preset.id,
            "job_id": "JOB-001",
            "start_time": now.isoformat(),
            "cycle_count": 100,
            "cut_time": 45.5
        },
        {
            "preset_id": preset.id,
            "job_id": "JOB-002",
            "start_time": now.isoformat(),
            "cycle_count": 150,
            "cut_time": 67.2
        }
    ]
    
    client.cookies.set("session", session_id)
    
    response = client.post(
        "/api/v1/tool-usage",
        json={"items": usage_records}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 2
    assert len(data["results"]) == 2
    assert data["error_count"] == 0
    
    # Verify data stored correctly
    assert data["results"][0]["preset_id"] == preset.id
    assert data["results"][0]["cycle_count"] == 100


@pytest.mark.integration
def test_create_validates_required_fields(client, db_session):
    """Test validation of required fields.
    
    Assumptions:
    - preset_id and start_time required
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly, ToolInstance, ToolPreset
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create assembly, instance, and preset
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
    
    now = datetime.now(UTC)
    usage_records = [
        {
            "preset_id": preset.id,
            "start_time": now.isoformat()
        },
        {
            # Missing required 'preset_id'
            "start_time": now.isoformat()
        }
    ]
    
    client.cookies.set("session", session_id)
    
    response = client.post(
        "/api/v1/tool-usage",
        json={"items": usage_records}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 1
    assert data["error_count"] == 1


@pytest.mark.integration
def test_bulk_read_tool_usage(client, db_session):
    """Test bulk read/list of tool usage records."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly, ToolInstance, ToolPreset, ToolUsage
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create assembly, instance, and preset
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
    
    # Create usage records
    for i in range(3):
        usage = ToolUsage(
            preset_id=preset.id,
            start_time=datetime.now(UTC),
            cycle_count=100 * (i + 1),
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
        db_session.add(usage)
    db_session.commit()
    
    client.cookies.set("session", session_id)
    
    response = client.get("/api/v1/tool-usage")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "items" in data
    assert len(data["items"]) == 3


@pytest.mark.integration
def test_bulk_update_tool_usage(client, db_session):
    """Test bulk update with version checking."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly, ToolInstance, ToolPreset, ToolUsage
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create assembly, instance, and preset
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
    
    # Create usage records
    usage1 = ToolUsage(
        preset_id=preset.id,
        start_time=datetime.now(UTC),
        cycle_count=100,
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=1
    )
    usage2 = ToolUsage(
        preset_id=preset.id,
        start_time=datetime.now(UTC),
        cycle_count=150,
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=1
    )
    db_session.add_all([usage1, usage2])
    db_session.commit()
    
    # Update both
    updates = [
        {
            "id": usage1.id,
            "version": 1,
            "end_time": datetime.now(UTC).isoformat(),
            "cut_time": 45.5
        },
        {
            "id": usage2.id,
            "version": 1,
            "cut_time": 67.2
        }
    ]
    
    client.cookies.set("session", session_id)
    
    response = client.put(
        "/api/v1/tool-usage",
        json={"items": updates}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 2
    assert data["error_count"] == 0
    assert data["results"][0]["version"] == 2


@pytest.mark.integration
def test_bulk_delete_tool_usage(client, db_session):
    """Test bulk delete of usage records."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly, ToolInstance, ToolPreset, ToolUsage
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create assembly, instance, and preset
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
    
    # Create usage records
    usage_records = []
    for i in range(3):
        usage = ToolUsage(
            preset_id=preset.id,
            start_time=datetime.now(UTC),
            cycle_count=100 * (i + 1),
            user_id=user.id,
            created_by=user.id,
            updated_by=user.id
        )
        usage_records.append(usage)
        db_session.add(usage)
    db_session.commit()
    
    # Delete first two
    client.cookies.set("session", session_id)
    
    response = client.request(
        "DELETE",
        "/api/v1/tool-usage",
        json={"ids": [usage_records[0].id, usage_records[1].id]}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 2
    assert data["error_count"] == 0
