# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Change detection API endpoints.

Provides REST API for clients to query changes since last sync.

Assumptions:
- Clients track last_synced_version or last_synced_timestamp per entity type
- Supports both version-based and timestamp-based sync
- Respects user permissions (data isolation)
- Returns changes in order (oldest first) for sequential processing
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from loobric_server.database.schema import (
    MachineRecord, ToolInstanceRecord, ToolCatalogRecord,
    ToolTableEntryRecord, ToolSetRecord,
)
from loobric_server.api.auth import get_db, require_auth
from loobric_server.change_detection import (
    get_changes_since_version, get_changes_since_timestamp, get_max_version
)
from loobric_server.auth.authorization import log_authorization_decision

router = APIRouter(prefix="/api/v1/changes", tags=["changes"])

# Entity type mapping — the v2 sectioned records (docs/TOOL_SCHEMA.md). Names
# match the table names. The legacy deep tables are retiring (REBOOT R6) and are
# no longer change-detectable here — change detection operates on v2 data (R12).
ENTITY_TYPES = {
    "machine_records": MachineRecord,
    "tool_instance_records": ToolInstanceRecord,
    "tool_catalog_records": ToolCatalogRecord,
    "tool_table_entry_records": ToolTableEntryRecord,
    "tool_set_records": ToolSetRecord,
}


class EntityChange(BaseModel):
    """Response model for entity change."""
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    version: int
    updated_at: datetime
    user_id: str
    created_by: str
    updated_by: str


class ChangesResponse(BaseModel):
    """Response model for changes query."""
    entity_type: str
    changes: list[dict]
    count: int
    max_version: int
    sync_method: Literal["version", "timestamp"]
    

@router.get("/{entity_type}/since-version")
async def get_changes_by_version(
    entity_type: str,
    since_version: int = Query(..., ge=0, description="Return entities with version > this value"),
    limit: Optional[int] = Query(100, ge=1, le=1000, description="Maximum number of results"),
    current_user = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get entities that changed since a specific version.
    
    Args:
        entity_type: Type of entity (tool_items, tool_assemblies, etc.)
        since_version: Return entities with version > this value
        limit: Maximum number of results (1-1000)
        current_user: Authenticated user
        db: Database session
        
    Returns:
        ChangesResponse with list of changed entities
        
    Assumptions:
    - Returns entities ordered by version (ascending)
    - Regular users only see their own entities
    - Admin users see all entities
    - Version 0 means "get all entities"
    """
    # Validate entity type
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity_type. Must be one of: {', '.join(ENTITY_TYPES.keys())}"
        )
    
    entity_class = ENTITY_TYPES[entity_type]
    
    # Log authorization decision
    log_authorization_decision(
        user_id=current_user.id,
        action="read",
        resource_type=entity_type,
        resource_id="changes",
        granted=True,
        reason=f"User requesting changes since version {since_version}"
    )
    
    # Get changes
    changes = get_changes_since_version(
        session=db,
        entity_type=entity_class,
        since_version=since_version,
        user_id=current_user.id,
        is_admin=current_user.is_admin,
        limit=limit
    )
    
    # Get max version for sync state tracking
    max_version = get_max_version(
        session=db,
        entity_type=entity_class,
        user_id=current_user.id,
        is_admin=current_user.is_admin
    )
    
    # Convert to dictionaries
    change_dicts = []
    for change in changes:
        # Get all attributes from the entity
        change_dict = {
            column.name: getattr(change, column.name)
            for column in change.__table__.columns
        }
        # Convert datetime objects to ISO format
        for key, value in change_dict.items():
            if isinstance(value, datetime):
                change_dict[key] = value.isoformat()
        change_dicts.append(change_dict)
    
    return {
        "entity_type": entity_type,
        "changes": change_dicts,
        "count": len(change_dicts),
        "max_version": max_version,
        "sync_method": "version"
    }


@router.get("/{entity_type}/since-timestamp")
async def get_changes_by_timestamp(
    entity_type: str,
    since_timestamp: datetime = Query(..., description="Return entities with updated_at > this value"),
    limit: Optional[int] = Query(100, ge=1, le=1000, description="Maximum number of results"),
    current_user = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get entities that changed since a specific timestamp.
    
    Args:
        entity_type: Type of entity (tool_items, tool_assemblies, etc.)
        since_timestamp: Return entities with updated_at > this value
        limit: Maximum number of results (1-1000)
        current_user: Authenticated user
        db: Database session
        
    Returns:
        ChangesResponse with list of changed entities
        
    Assumptions:
    - Returns entities ordered by updated_at (ascending)
    - Regular users only see their own entities
    - Admin users see all entities
    """
    # Validate entity type
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity_type. Must be one of: {', '.join(ENTITY_TYPES.keys())}"
        )
    
    entity_class = ENTITY_TYPES[entity_type]
    
    # Log authorization decision
    log_authorization_decision(
        user_id=current_user.id,
        action="read",
        resource_type=entity_type,
        resource_id="changes",
        granted=True,
        reason=f"User requesting changes since {since_timestamp.isoformat()}"
    )
    
    # Get changes
    changes = get_changes_since_timestamp(
        session=db,
        entity_type=entity_class,
        since_timestamp=since_timestamp,
        user_id=current_user.id,
        is_admin=current_user.is_admin,
        limit=limit
    )
    
    # Get max version for sync state tracking
    max_version = get_max_version(
        session=db,
        entity_type=entity_class,
        user_id=current_user.id,
        is_admin=current_user.is_admin
    )
    
    # Convert to dictionaries
    change_dicts = []
    for change in changes:
        # Get all attributes from the entity
        change_dict = {
            column.name: getattr(change, column.name)
            for column in change.__table__.columns
        }
        # Convert datetime objects to ISO format
        for key, value in change_dict.items():
            if isinstance(value, datetime):
                change_dict[key] = value.isoformat()
        change_dicts.append(change_dict)
    
    return {
        "entity_type": entity_type,
        "changes": change_dicts,
        "count": len(change_dicts),
        "max_version": max_version,
        "sync_method": "timestamp"
    }


@router.get("/{entity_type}/max-version")
async def get_entity_max_version(
    entity_type: str,
    current_user = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Get the maximum version number for an entity type.
    
    Args:
        entity_type: Type of entity (tool_items, tool_assemblies, etc.)
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Dictionary with max_version
        
    Assumptions:
    - Used by clients to check sync state
    - Returns 0 if no entities exist
    - Respects user permission filtering
    """
    # Validate entity type
    if entity_type not in ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity_type. Must be one of: {', '.join(ENTITY_TYPES.keys())}"
        )
    
    entity_class = ENTITY_TYPES[entity_type]
    
    # Get max version
    max_version = get_max_version(
        session=db,
        entity_type=entity_class,
        user_id=current_user.id,
        is_admin=current_user.is_admin
    )
    
    return {
        "entity_type": entity_type,
        "max_version": max_version
    }
