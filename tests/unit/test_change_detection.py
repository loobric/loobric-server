# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Unit tests for change detection functionality.

Tests querying entities by version and timestamp for synchronization.

Assumptions:
- All entities have version field (incremented on update)
- All entities have updated_at timestamp
- Clients track last_synced_version or last_synced_timestamp
- Change detection respects user permissions (data isolation)
- Supports filtering by entity type
"""
import pytest
from datetime import datetime, UTC, timedelta


@pytest.mark.unit
def test_get_changes_since_version(db_session):
    """Test retrieving entities changed since specific version.
    
    Assumptions:
    - Returns entities with version > specified version
    - Includes newly created and updated entities
    - Respects user_id filtering for non-admin users
    """
    from loobric_server.database.schema import ToolItem
    from loobric_server.change_detection import get_changes_since_version
    
    user_id = "user-123"
    
    # Create items with different versions
    item1 = ToolItem(
        id="item-1",
        type="cutting_tool",
        version=1,
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id
    )
    item2 = ToolItem(
        id="item-2",
        type="cutting_tool",
        version=2,
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id
    )
    item3 = ToolItem(
        id="item-3",
        type="cutting_tool",
        version=3,
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id
    )
    
    db_session.add_all([item1, item2, item3])
    db_session.commit()
    
    # Get changes since version 1
    changes = get_changes_since_version(
        session=db_session,
        entity_type=ToolItem,
        since_version=1,
        user_id=user_id,
        is_admin=False
    )
    
    # Should return items with version > 1 (items 2 and 3)
    assert len(changes) == 2
    versions = [item.version for item in changes]
    assert 2 in versions
    assert 3 in versions


@pytest.mark.unit
def test_get_changes_since_timestamp(db_session):
    """Test retrieving entities changed since specific timestamp.
    
    Assumptions:
    - Returns entities with updated_at > specified timestamp
    - Includes newly created and updated entities
    - Respects user_id filtering
    """
    from loobric_server.database.schema import ToolItem
    from loobric_server.change_detection import get_changes_since_timestamp
    
    user_id = "user-123"
    base_time = datetime.now(UTC)
    
    # Create items with different timestamps
    item1 = ToolItem(
        id="item-1",
        type="cutting_tool",
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id,
        updated_at=base_time - timedelta(hours=3)
    )
    item2 = ToolItem(
        id="item-2",
        type="cutting_tool",
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id,
        updated_at=base_time - timedelta(hours=1)
    )
    item3 = ToolItem(
        id="item-3",
        type="cutting_tool",
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id,
        updated_at=base_time
    )
    
    db_session.add_all([item1, item2, item3])
    db_session.commit()
    
    # Get changes since 2 hours ago
    since_timestamp = base_time - timedelta(hours=2)
    changes = get_changes_since_timestamp(
        session=db_session,
        entity_type=ToolItem,
        since_timestamp=since_timestamp,
        user_id=user_id,
        is_admin=False
    )
    
    # Should return items 2 and 3 (updated within last 2 hours)
    assert len(changes) == 2


@pytest.mark.unit
def test_change_detection_respects_user_isolation(db_session):
    """Test that non-admin users only see their own changes.
    
    Assumptions:
    - Regular users filtered by user_id
    - Admin users see all changes
    """
    from loobric_server.database.schema import ToolItem
    from loobric_server.change_detection import get_changes_since_version
    
    user1_id = "user-1"
    user2_id = "user-2"
    
    # Create items for different users
    item1 = ToolItem(
        id="item-1",
        type="cutting_tool",
        version=2,
        user_id=user1_id,
        created_by=user1_id,
        updated_by=user1_id
    )
    item2 = ToolItem(
        id="item-2",
        type="cutting_tool",
        version=2,
        user_id=user2_id,
        created_by=user2_id,
        updated_by=user2_id
    )
    
    db_session.add_all([item1, item2])
    db_session.commit()
    
    # User 1 should only see their changes
    changes = get_changes_since_version(
        session=db_session,
        entity_type=ToolItem,
        since_version=1,
        user_id=user1_id,
        is_admin=False
    )
    
    assert len(changes) == 1
    assert changes[0].user_id == user1_id


@pytest.mark.unit
def test_admin_sees_all_changes(db_session):
    """Test that admin users see changes from all users.
    
    Assumptions:
    - Admin users not filtered by user_id
    - Returns changes from all users
    """
    from loobric_server.database.schema import ToolItem
    from loobric_server.change_detection import get_changes_since_version
    
    user1_id = "user-1"
    user2_id = "user-2"
    admin_id = "admin-1"
    
    # Create items for different users
    item1 = ToolItem(
        id="item-1",
        type="cutting_tool",
        version=2,
        user_id=user1_id,
        created_by=user1_id,
        updated_by=user1_id
    )
    item2 = ToolItem(
        id="item-2",
        type="cutting_tool",
        version=2,
        user_id=user2_id,
        created_by=user2_id,
        updated_by=user2_id
    )
    
    db_session.add_all([item1, item2])
    db_session.commit()
    
    # Admin should see all changes
    changes = get_changes_since_version(
        session=db_session,
        entity_type=ToolItem,
        since_version=1,
        user_id=admin_id,
        is_admin=True
    )
    
    assert len(changes) == 2


@pytest.mark.unit
def test_change_detection_with_limit(db_session):
    """Test limiting number of results returned.
    
    Assumptions:
    - Supports pagination with limit parameter
    - Results ordered by version (ascending)
    """
    from loobric_server.database.schema import ToolItem
    from loobric_server.change_detection import get_changes_since_version
    
    user_id = "user-123"
    
    # Create many items
    items = []
    for i in range(10):
        item = ToolItem(
            id=f"item-{i}",
            type="cutting_tool",
            version=i + 2,  # versions 2-11
            user_id=user_id,
            created_by=user_id,
            updated_by=user_id
        )
        items.append(item)
    
    db_session.add_all(items)
    db_session.commit()
    
    # Get changes with limit
    changes = get_changes_since_version(
        session=db_session,
        entity_type=ToolItem,
        since_version=1,
        user_id=user_id,
        is_admin=False,
        limit=5
    )
    
    assert len(changes) == 5


@pytest.mark.unit
def test_get_max_version(db_session):
    """Test retrieving maximum version for entity type.
    
    Assumptions:
    - Returns highest version number across all entities of type
    - Used by clients to track sync state
    - Respects user_id filtering
    """
    from loobric_server.database.schema import ToolItem
    from loobric_server.change_detection import get_max_version
    
    user_id = "user-123"
    
    # Create items with different versions
    item1 = ToolItem(
        id="item-1",
        type="cutting_tool",
        version=5,
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id
    )
    item2 = ToolItem(
        id="item-2",
        type="cutting_tool",
        version=12,
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id
    )
    item3 = ToolItem(
        id="item-3",
        type="cutting_tool",
        version=8,
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id
    )
    
    db_session.add_all([item1, item2, item3])
    db_session.commit()
    
    max_ver = get_max_version(
        session=db_session,
        entity_type=ToolItem,
        user_id=user_id,
        is_admin=False
    )
    
    assert max_ver == 12


@pytest.mark.unit
def test_get_max_version_returns_zero_when_empty(db_session):
    """Test get_max_version returns 0 when no entities exist.
    
    Assumptions:
    - Returns 0 for empty result set
    - Clients can start with version 0
    """
    from loobric_server.database.schema import ToolItem
    from loobric_server.change_detection import get_max_version
    
    max_ver = get_max_version(
        session=db_session,
        entity_type=ToolItem,
        user_id="user-123",
        is_admin=False
    )
    
    assert max_ver == 0


@pytest.mark.unit
def test_changes_ordered_by_version(db_session):
    """Test that changes are returned in version order.
    
    Assumptions:
    - Results ordered by version ascending
    - Allows clients to process changes sequentially
    """
    from loobric_server.database.schema import ToolItem
    from loobric_server.change_detection import get_changes_since_version
    
    user_id = "user-123"
    
    # Create items in non-sequential order
    item3 = ToolItem(
        id="item-3",
        type="cutting_tool",
        version=5,
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id
    )
    item1 = ToolItem(
        id="item-1",
        type="cutting_tool",
        version=2,
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id
    )
    item2 = ToolItem(
        id="item-2",
        type="cutting_tool",
        version=3,
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id
    )
    
    db_session.add_all([item3, item1, item2])
    db_session.commit()
    
    changes = get_changes_since_version(
        session=db_session,
        entity_type=ToolItem,
        since_version=1,
        user_id=user_id,
        is_admin=False
    )
    
    # Should be ordered by version
    versions = [item.version for item in changes]
    assert versions == sorted(versions)
    assert versions == [2, 3, 5]


@pytest.mark.unit
def test_changes_ordered_by_timestamp(db_session):
    """Test that timestamp-based changes are returned in time order.
    
    Assumptions:
    - Results ordered by updated_at ascending
    - Oldest changes first
    """
    from loobric_server.database.schema import ToolItem
    from loobric_server.change_detection import get_changes_since_timestamp
    
    user_id = "user-123"
    base_time = datetime.now(UTC)
    
    # Create items with different timestamps
    item3 = ToolItem(
        id="item-3",
        type="cutting_tool",
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id,
        updated_at=base_time - timedelta(minutes=10)
    )
    item1 = ToolItem(
        id="item-1",
        type="cutting_tool",
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id,
        updated_at=base_time - timedelta(minutes=30)
    )
    item2 = ToolItem(
        id="item-2",
        type="cutting_tool",
        user_id=user_id,
        created_by=user_id,
        updated_by=user_id,
        updated_at=base_time - timedelta(minutes=20)
    )
    
    db_session.add_all([item3, item1, item2])
    db_session.commit()
    
    since_timestamp = base_time - timedelta(hours=1)
    changes = get_changes_since_timestamp(
        session=db_session,
        entity_type=ToolItem,
        since_timestamp=since_timestamp,
        user_id=user_id,
        is_admin=False
    )
    
    # Should be ordered by timestamp (oldest first)
    timestamps = [item.updated_at for item in changes]
    assert timestamps == sorted(timestamps)
