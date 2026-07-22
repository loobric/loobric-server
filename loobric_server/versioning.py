# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Version management for entities with history tracking.

Provides snapshot and restore functionality for versioned entities.
"""
from datetime import datetime, UTC
from typing import Optional
from sqlalchemy.orm import Session

from loobric_server.database.schema import ToolSet, ToolSetHistory


def snapshot_tool_set(
    session: Session,
    tool_set: ToolSet,
    changed_by: str,
    change_summary: Optional[str] = None
) -> ToolSetHistory:
    """Create a snapshot of a ToolSet before modification.
    
    Args:
        session: Database session
        tool_set: ToolSet to snapshot
        changed_by: User ID making the change
        change_summary: Optional description of what changed
        
    Returns:
        ToolSetHistory: Created history record
        
    Assumptions:
    - Called before updating ToolSet
    - Captures complete state at current version
    - Immutable once created
    """
    snapshot = {
        "id": tool_set.id,
        "name": tool_set.name,
        "description": tool_set.description,
        "type": tool_set.type,
        "machine_id": tool_set.machine_id,
        "job_id": tool_set.job_id,
        "members": tool_set.members,
        "capacity": tool_set.capacity,
        "status": tool_set.status,
        "activation": tool_set.activation,
        "user_id": tool_set.user_id,
        "created_by": tool_set.created_by,
        "created_at": tool_set.created_at.isoformat() if tool_set.created_at else None,
        "updated_at": tool_set.updated_at.isoformat() if tool_set.updated_at else None,
    }
    
    history = ToolSetHistory(
        tool_set_id=tool_set.id,
        version=tool_set.version,
        snapshot=snapshot,
        changed_by=changed_by,
        change_summary=change_summary
    )
    
    session.add(history)
    return history


def get_tool_set_history(
    session: Session,
    tool_set_id: str,
    user_id: str
) -> list[ToolSetHistory]:
    """Get all history records for a ToolSet.
    
    Args:
        session: Database session
        tool_set_id: ToolSet ID
        user_id: User ID for authorization
        
    Returns:
        list[ToolSetHistory]: History records ordered by version
    """
    # Verify ownership
    tool_set = session.get(ToolSet, tool_set_id)
    if not tool_set or tool_set.user_id != user_id:
        return []
    
    return session.query(ToolSetHistory).filter(
        ToolSetHistory.tool_set_id == tool_set_id
    ).order_by(ToolSetHistory.version.desc()).all()


def restore_tool_set(
    session: Session,
    tool_set_id: str,
    target_version: int,
    user_id: str
) -> Optional[ToolSet]:
    """Restore a ToolSet to a previous version.
    
    Args:
        session: Database session
        tool_set_id: ToolSet ID
        target_version: Version to restore to
        user_id: User ID performing restore
        
    Returns:
        ToolSet: Updated ToolSet, or None if not found
        
    Assumptions:
    - Creates new history snapshot before restore
    - Increments version (restore is a new version)
    - Only restores data fields, not metadata (created_at, etc.)
    """
    tool_set = session.query(ToolSet).filter(
        ToolSet.id == tool_set_id,
        ToolSet.user_id == user_id
    ).first()
    
    if not tool_set:
        return None
    
    # Get target version snapshot
    history = session.query(ToolSetHistory).filter(
        ToolSetHistory.tool_set_id == tool_set_id,
        ToolSetHistory.version == target_version
    ).first()
    
    if not history:
        return None
    
    # Snapshot current state before restore
    snapshot_tool_set(
        session, 
        tool_set, 
        user_id, 
        f"Before restore to version {target_version}"
    )
    
    # Restore data from snapshot
    snapshot = history.snapshot
    tool_set.name = snapshot.get("name")
    tool_set.description = snapshot.get("description")
    tool_set.type = snapshot.get("type")
    tool_set.machine_id = snapshot.get("machine_id")
    tool_set.job_id = snapshot.get("job_id")
    tool_set.members = snapshot.get("members", [])
    tool_set.capacity = snapshot.get("capacity")
    tool_set.status = snapshot.get("status")
    tool_set.activation = snapshot.get("activation")
    
    # Update metadata
    tool_set.updated_by = user_id
    tool_set.updated_at = datetime.now(UTC)
    tool_set.version += 1
    
    session.flush()
    
    # Create history record for the restore
    snapshot_tool_set(
        session,
        tool_set,
        user_id,
        f"Restored from version {target_version}"
    )
    
    return tool_set


def compare_versions(
    session: Session,
    tool_set_id: str,
    version_a: int,
    version_b: int,
    user_id: str
) -> Optional[dict]:
    """Compare two versions of a ToolSet.
    
    Args:
        session: Database session
        tool_set_id: ToolSet ID
        version_a: First version
        version_b: Second version
        user_id: User ID for authorization
        
    Returns:
        dict: Comparison showing differences, or None if not found
    """
    # Verify ownership
    tool_set = session.get(ToolSet, tool_set_id)
    if not tool_set or tool_set.user_id != user_id:
        return None
    
    hist_a = session.query(ToolSetHistory).filter(
        ToolSetHistory.tool_set_id == tool_set_id,
        ToolSetHistory.version == version_a
    ).first()
    
    hist_b = session.query(ToolSetHistory).filter(
        ToolSetHistory.tool_set_id == tool_set_id,
        ToolSetHistory.version == version_b
    ).first()
    
    if not hist_a or not hist_b:
        return None
    
    snap_a = hist_a.snapshot
    snap_b = hist_b.snapshot
    
    # Find differences
    differences = {}
    fields = ["name", "description", "type", "machine_id", "job_id", "members", "capacity", "status", "activation"]
    
    for field in fields:
        val_a = snap_a.get(field)
        val_b = snap_b.get(field)
        if val_a != val_b:
            differences[field] = {
                f"version_{version_a}": val_a,
                f"version_{version_b}": val_b
            }
    
    return {
        "tool_set_id": tool_set_id,
        "version_a": version_a,
        "version_b": version_b,
        "differences": differences,
        "total_changes": len(differences)
    }
