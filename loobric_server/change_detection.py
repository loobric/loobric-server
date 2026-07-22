# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Change detection functions for entity synchronization.

Provides version-based and timestamp-based change queries for clients to sync data.

Assumptions:
- All entities have version field (starts at 1, increments on update)
- All entities have updated_at timestamp
- Clients track last_synced_version or last_synced_timestamp
- Respects user permissions (data isolation for non-admin users)
- Results ordered by version/timestamp ascending for sequential processing
"""
from datetime import datetime
from typing import Type, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from loobric_server.database.schema import Base


def get_changes_since_version(
    session: Session,
    entity_type: Type[Base],
    since_version: int,
    user_id: str,
    is_admin: bool = False,
    limit: Optional[int] = None
) -> List[Base]:
    """Get entities that have changed since a specific version.
    
    Args:
        session: Database session
        entity_type: SQLAlchemy model class (e.g., ToolItem)
        since_version: Return entities with version > this value
        user_id: User ID for permission filtering
        is_admin: Whether user is admin (sees all data)
        limit: Maximum number of results to return
        
    Returns:
        List of entity objects ordered by version ascending
        
    Assumptions:
    - Regular users only see their own entities
    - Admin users see all entities
    - Results ordered by version for sequential processing
    - Version 0 means "get all entities"
    """
    query = session.query(entity_type)
    
    # Filter by version
    query = query.filter(entity_type.version > since_version)
    
    # Apply user permission filtering
    if not is_admin:
        query = query.filter(entity_type.user_id == user_id)
    
    # Order by version ascending (oldest changes first)
    query = query.order_by(entity_type.version.asc())
    
    # Apply limit if specified
    if limit:
        query = query.limit(limit)
    
    return query.all()


def get_changes_since_timestamp(
    session: Session,
    entity_type: Type[Base],
    since_timestamp: datetime,
    user_id: str,
    is_admin: bool = False,
    limit: Optional[int] = None
) -> List[Base]:
    """Get entities that have changed since a specific timestamp.
    
    Args:
        session: Database session
        entity_type: SQLAlchemy model class
        since_timestamp: Return entities with updated_at > this value
        user_id: User ID for permission filtering
        is_admin: Whether user is admin
        limit: Maximum number of results to return
        
    Returns:
        List of entity objects ordered by updated_at ascending
        
    Assumptions:
    - Regular users only see their own entities
    - Admin users see all entities
    - Results ordered by timestamp for sequential processing
    """
    query = session.query(entity_type)
    
    # Filter by timestamp
    query = query.filter(entity_type.updated_at > since_timestamp)
    
    # Apply user permission filtering
    if not is_admin:
        query = query.filter(entity_type.user_id == user_id)
    
    # Order by updated_at ascending (oldest changes first)
    query = query.order_by(entity_type.updated_at.asc())
    
    # Apply limit if specified
    if limit:
        query = query.limit(limit)
    
    return query.all()


def get_max_version(
    session: Session,
    entity_type: Type[Base],
    user_id: str,
    is_admin: bool = False
) -> int:
    """Get the maximum version number for an entity type.
    
    Args:
        session: Database session
        entity_type: SQLAlchemy model class
        user_id: User ID for permission filtering
        is_admin: Whether user is admin
        
    Returns:
        Maximum version number, or 0 if no entities exist
        
    Assumptions:
    - Used by clients to track sync state
    - Returns 0 for empty result set (allows starting from version 0)
    - Respects user permission filtering
    """
    query = session.query(func.max(entity_type.version))
    
    # Apply user permission filtering
    if not is_admin:
        query = query.filter(entity_type.user_id == user_id)
    
    result = query.scalar()
    
    # Return 0 if no entities exist
    return result if result is not None else 0
