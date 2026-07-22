# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for ToolPreset API - FreeCAD/LinuxCNC use cases.

Tests presets created WITHOUT instance_id (machine-specific tool configs
that reference tools by description/metadata rather than physical instances).

This covers the bug where API required instance_id even though DB schema
allows NULL, breaking FreeCAD and LinuxCNC clients.
"""
import pytest


@pytest.mark.integration
def test_create_preset_without_instance_id(client, db_session):
    """Test creating presets without instance_id (FreeCAD/LinuxCNC use case).
    
    Assumptions:
    - instance_id is optional (nullable in schema)
    - Presets can reference tools by description/metadata
    - Used by FreeCAD libraries and LinuxCNC tool tables
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # FreeCAD-style presets (no instance_id, has description + metadata)
    presets = [
        {
            "machine_id": "freecad_default",
            "tool_number": 1,
            "description": "5mm Drill",
            "metadata": {
                "source": "freecad",
                "library_name": "Test Library",
                "tool_path": "drill_5mm.fctb"
            }
        },
        {
            "machine_id": "freecad_default",
            "tool_number": 2,
            "description": "6mm Endmill",
            "metadata": {
                "source": "freecad",
                "library_name": "Test Library",
                "tool_path": "endmill_6mm.fctb"
            }
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
    assert data["error_count"] == 0
    assert len(data["results"]) == 2
    
    # Verify data stored correctly
    assert data["results"][0]["machine_id"] == "freecad_default"
    assert data["results"][0]["tool_number"] == 1
    assert data["results"][0]["description"] == "5mm Drill"
    assert data["results"][0]["metadata"]["source"] == "freecad"
    assert data["results"][0]["instance_id"] is None


@pytest.mark.integration
def test_create_linuxcnc_preset_with_offsets(client, db_session):
    """Test creating LinuxCNC-style preset with offsets but no instance_id.
    
    LinuxCNC tool tables include offsets and metadata but don't link
    to physical instances.
    """
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # LinuxCNC-style preset
    presets = [
        {
            "machine_id": "mill01",
            "tool_number": 1,
            "description": "5mm Drill HSS",
            "offsets": {
                "z": -50.0,
                "z_unit": "mm"
            },
            "metadata": {
                "source": "linuxcnc",
                "diameter": 5.0,
                "diameter_unit": "mm"
            }
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
    assert data["results"][0]["offsets"]["z"] == -50.0
    assert data["results"][0]["metadata"]["diameter"] == 5.0


@pytest.mark.integration
def test_query_presets_by_machine_returns_all_types(client, db_session):
    """Test querying returns both presets with and without instance_id."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolAssembly, ToolInstance, ToolPreset
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create instance-based preset
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
    
    preset_with_instance = ToolPreset(
        machine_id="test_machine",
        tool_number=1,
        instance_id=instance.id,
        description="Physical Tool",
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(preset_with_instance)
    
    # Create FreeCAD-style preset (no instance)
    preset_without_instance = ToolPreset(
        machine_id="test_machine",
        tool_number=2,
        instance_id=None,
        description="Virtual Tool",
        preset_metadata={"source": "freecad"},
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id
    )
    db_session.add(preset_without_instance)
    db_session.commit()
    
    client.cookies.set("session", session_id)
    
    response = client.get("/api/v1/tool-presets?machine_id=test_machine")
    
    assert response.status_code == 200
    data = response.json()
    
    assert len(data["items"]) == 2
    
    # Find each preset
    with_instance = next(p for p in data["items"] if p["tool_number"] == 1)
    without_instance = next(p for p in data["items"] if p["tool_number"] == 2)
    
    assert with_instance["instance_id"] == instance.id
    assert without_instance["instance_id"] is None
    assert without_instance["metadata"]["source"] == "freecad"


@pytest.mark.integration
def test_update_preset_metadata(client, db_session):
    """Test updating metadata field on existing preset."""
    from loobric_server.auth.user import create_user
    from loobric_server.api.auth import create_session
    from loobric_server.database.schema import ToolPreset
    
    user = create_user(db_session, "test@example.com", "Password123")
    session_id = create_session(user.id)
    
    # Create preset with metadata
    preset = ToolPreset(
        machine_id="test_machine",
        tool_number=1,
        description="Test Tool",
        preset_metadata={"version": 1, "source": "freecad"},
        user_id=user.id,
        created_by=user.id,
        updated_by=user.id,
        version=1
    )
    db_session.add(preset)
    db_session.commit()
    
    # Update metadata
    updates = [
        {
            "id": preset.id,
            "version": 1,
            "metadata": {"version": 2, "source": "freecad", "updated": True}
        }
    ]
    
    client.cookies.set("session", session_id)
    
    response = client.put(
        "/api/v1/tool-presets",
        json={"items": updates}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["success_count"] == 1
    assert data["results"][0]["metadata"]["version"] == 2
    assert data["results"][0]["metadata"]["updated"] is True
