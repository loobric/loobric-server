# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Unit tests for ToolSet versioning functionality.

Tests snapshot, history, restore, and comparison features.

Assumptions:
- Each update creates a snapshot
- Snapshots are immutable
- Restore creates new version
- History is user-scoped
"""
import pytest
from datetime import datetime, UTC


@pytest.mark.unit
def test_snapshot_tool_set(db_session):
    """Test creating a snapshot of a ToolSet.
    
    Assumptions:
    - Snapshot captures complete state
    - Version number recorded
    - Immutable once created
    """
    from loobric_server.database.schema import ToolSet, ToolSetHistory
    from loobric_server.versioning import snapshot_tool_set
    
    # Create a tool set
    tool_set = ToolSet(
        name="Test Set",
        type="template",
        members=[{"preset_id": "p1", "tool_number": 1}],
        status="draft",
        user_id="user-123",
        created_by="user-123",
        updated_by="user-123",
        version=1
    )
    db_session.add(tool_set)
    db_session.commit()
    
    # Create snapshot
    history = snapshot_tool_set(db_session, tool_set, "user-123", "Initial snapshot")
    db_session.commit()
    
    assert history.tool_set_id == tool_set.id
    assert history.version == 1
    assert history.changed_by == "user-123"
    assert history.change_summary == "Initial snapshot"
    assert history.snapshot["name"] == "Test Set"
    assert len(history.snapshot["members"]) == 1


@pytest.mark.unit
def test_get_tool_set_history(db_session):
    """Test retrieving version history for a ToolSet.
    
    Assumptions:
    - Returns all versions for a set
    - Ordered by version desc
    - User-scoped access
    """
    from loobric_server.database.schema import ToolSet
    from loobric_server.versioning import snapshot_tool_set, get_tool_set_history
    
    # Create tool set
    tool_set = ToolSet(
        name="Test Set",
        type="template",
        members=[],
        status="draft",
        user_id="user-123",
        created_by="user-123",
        updated_by="user-123",
        version=1
    )
    db_session.add(tool_set)
    db_session.commit()
    
    # Create multiple snapshots
    snapshot_tool_set(db_session, tool_set, "user-123", "Version 1")
    tool_set.version = 2
    snapshot_tool_set(db_session, tool_set, "user-123", "Version 2")
    tool_set.version = 3
    snapshot_tool_set(db_session, tool_set, "user-123", "Version 3")
    db_session.commit()
    
    # Get history
    history = get_tool_set_history(db_session, tool_set.id, "user-123")
    
    assert len(history) == 3
    assert history[0].version == 3  # Newest first
    assert history[1].version == 2
    assert history[2].version == 1


@pytest.mark.unit
def test_get_history_access_control(db_session):
    """Test that users can only see their own history.
    
    Assumptions:
    - User-scoped access
    - Empty list for unauthorized access
    """
    from loobric_server.database.schema import ToolSet
    from loobric_server.versioning import get_tool_set_history
    
    tool_set = ToolSet(
        name="Test Set",
        type="template",
        members=[],
        status="draft",
        user_id="user-123",
        created_by="user-123",
        updated_by="user-123"
    )
    db_session.add(tool_set)
    db_session.commit()
    
    # Try to access with different user
    history = get_tool_set_history(db_session, tool_set.id, "user-456")
    
    assert len(history) == 0


@pytest.mark.unit
def test_restore_tool_set(db_session):
    """Test restoring a ToolSet to a previous version.
    
    Assumptions:
    - Restores data fields from snapshot
    - Creates new version (increments)
    - Snapshots before and after restore
    """
    from loobric_server.database.schema import ToolSet
    from loobric_server.versioning import snapshot_tool_set, restore_tool_set, get_tool_set_history
    
    # Create tool set
    tool_set = ToolSet(
        name="Original Name",
        type="template",
        members=[{"preset_id": "p1"}],
        status="draft",
        user_id="user-123",
        created_by="user-123",
        updated_by="user-123",
        version=1
    )
    db_session.add(tool_set)
    db_session.commit()
    
    # Snapshot version 1
    snapshot_tool_set(db_session, tool_set, "user-123")
    db_session.commit()
    
    # Modify to version 2
    tool_set.name = "Modified Name"
    tool_set.members = [{"preset_id": "p1"}, {"preset_id": "p2"}]
    tool_set.version = 2
    db_session.commit()
    
    # Restore to version 1
    restored = restore_tool_set(db_session, tool_set.id, 1, "user-123")
    db_session.commit()
    
    assert restored.name == "Original Name"
    assert len(restored.members) == 1
    assert restored.version == 3  # New version created
    
    # Check history contains restore records
    history = get_tool_set_history(db_session, tool_set.id, "user-123")
    assert len(history) >= 2  # Before and after restore


@pytest.mark.unit
def test_restore_nonexistent_version(db_session):
    """Test restoring to a nonexistent version returns None.
    
    Assumptions:
    - Returns None if version not found
    - No changes made
    """
    from loobric_server.database.schema import ToolSet
    from loobric_server.versioning import restore_tool_set
    
    tool_set = ToolSet(
        name="Test Set",
        type="template",
        members=[],
        status="draft",
        user_id="user-123",
        created_by="user-123",
        updated_by="user-123",
        version=1
    )
    db_session.add(tool_set)
    db_session.commit()
    
    # Try to restore to nonexistent version
    result = restore_tool_set(db_session, tool_set.id, 99, "user-123")
    
    assert result is None
    
    # Verify original unchanged
    db_session.refresh(tool_set)
    assert tool_set.version == 1


@pytest.mark.unit
def test_compare_versions(db_session):
    """Test comparing two versions of a ToolSet.
    
    Assumptions:
    - Shows differences between versions
    - Only changed fields included
    - Returns None if versions not found
    """
    from loobric_server.database.schema import ToolSet
    from loobric_server.versioning import snapshot_tool_set, compare_versions
    
    # Create tool set
    tool_set = ToolSet(
        name="Version 1 Name",
        description="Version 1 Desc",
        type="template",
        members=[{"preset_id": "p1"}],
        status="draft",
        user_id="user-123",
        created_by="user-123",
        updated_by="user-123",
        version=1
    )
    db_session.add(tool_set)
    db_session.commit()
    
    # Snapshot version 1
    snapshot_tool_set(db_session, tool_set, "user-123")
    
    # Modify to version 2
    tool_set.name = "Version 2 Name"
    tool_set.members = [{"preset_id": "p1"}, {"preset_id": "p2"}]
    tool_set.version = 2
    snapshot_tool_set(db_session, tool_set, "user-123")
    db_session.commit()
    
    # Compare versions
    comparison = compare_versions(db_session, tool_set.id, 1, 2, "user-123")
    
    assert comparison is not None
    assert comparison["tool_set_id"] == tool_set.id
    assert "name" in comparison["differences"]
    assert "members" in comparison["differences"]
    assert "description" not in comparison["differences"]  # Unchanged
    
    assert comparison["differences"]["name"]["version_1"] == "Version 1 Name"
    assert comparison["differences"]["name"]["version_2"] == "Version 2 Name"


@pytest.mark.unit
def test_compare_identical_versions(db_session):
    """Test comparing identical versions shows no differences.
    
    Assumptions:
    - Empty differences dict if no changes
    - total_changes is 0
    """
    from loobric_server.database.schema import ToolSet
    from loobric_server.versioning import snapshot_tool_set, compare_versions
    
    tool_set = ToolSet(
        name="Test Set",
        type="template",
        members=[],
        status="draft",
        user_id="user-123",
        created_by="user-123",
        updated_by="user-123",
        version=1
    )
    db_session.add(tool_set)
    db_session.commit()
    
    # Create two identical snapshots
    snapshot_tool_set(db_session, tool_set, "user-123")
    tool_set.version = 2
    snapshot_tool_set(db_session, tool_set, "user-123")
    db_session.commit()
    
    # Compare
    comparison = compare_versions(db_session, tool_set.id, 1, 2, "user-123")
    
    assert comparison["total_changes"] == 0
    assert len(comparison["differences"]) == 0
