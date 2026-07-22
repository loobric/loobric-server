# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Audit log query API endpoints.

Provides role-based access to audit logs:
- Regular users can only query their own logs
- Admin users can query all logs from all users
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
import structlog

from loobric_server.database.schema import AuditLog, User
from loobric_server.api.auth import get_db, require_auth
from loobric_server.auth.authorization import log_authorization_decision

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/audit-logs", tags=["audit-logs"])


@router.get("")
async def query_audit_logs(
    user_id: Optional[str] = Query(None, description="Filter by user ID (admin only)"),
    operation: Optional[str] = Query(None, description="Filter by operation (CREATE, UPDATE, DELETE, etc.)"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
    result: Optional[str] = Query(None, description="Filter by result (success, error)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of logs to return"),
    offset: int = Query(0, ge=0, description="Number of logs to skip"),
    current_user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """Query audit logs with role-based filtering.
    
    Regular users can only see their own logs.
    Admin users can see all logs and filter by user_id.
    
    Args:
        user_id: Filter by user ID (admin only)
        operation: Filter by operation type
        entity_type: Filter by entity type
        entity_id: Filter by specific entity ID
        result: Filter by result status
        limit: Maximum number of results (1-1000)
        offset: Number of results to skip for pagination
        current_user: Authenticated user
        db: Database session
        
    Returns:
        Dictionary with logs array and metadata
    """
    # Build query
    query = db.query(AuditLog)
    
    # Role-based filtering
    if current_user.is_admin:
        # Admin can see all logs, optionally filter by user_id
        log_authorization_decision(
            user_id=current_user.id,
            action="read",
            resource_type="audit_logs",
            resource_id="all",
            granted=True,
            reason="Admin user can access all audit logs"
        )
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
    else:
        # Regular users can only see their own logs
        log_authorization_decision(
            user_id=current_user.id,
            action="read",
            resource_type="audit_logs",
            resource_id=current_user.id,
            granted=True,
            reason="User can access their own audit logs"
        )
        query = query.filter(AuditLog.user_id == current_user.id)
    
    # Apply additional filters
    if operation:
        query = query.filter(AuditLog.operation == operation)
    
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    
    if entity_id:
        query = query.filter(AuditLog.entity_id == entity_id)
    
    if result:
        query = query.filter(AuditLog.result == result)
    
    # Get total count before pagination
    total_count = query.count()
    
    # Apply ordering and pagination
    query = query.order_by(AuditLog.timestamp.desc())
    query = query.offset(offset).limit(limit)
    
    # Execute query
    logs = query.all()
    
    # Convert to dictionaries
    log_dicts = []
    for log in logs:
        log_dicts.append({
            "id": log.id,
            "user_id": log.user_id,
            "operation": log.operation,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "changes": log.changes,
            "result": log.result,
            "timestamp": log.timestamp.isoformat()
        })
    
    return {
        "logs": log_dicts,
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "is_admin": current_user.is_admin
    }
