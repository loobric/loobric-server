# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Audit logging functionality.

Provides functions to create immutable audit logs for compliance.

Assumptions:
- Audit logs track all data modifications
- Required fields: user_id, timestamp, operation, entity_type, entity_id, result
- Audit logs are immutable (write-once)
- JSON-formatted for structured querying
- 7-year retention for compliance
"""
from typing import Optional, List
from datetime import datetime, UTC
from sqlalchemy.orm import Session
from uuid import uuid4

from loobric_server.database.schema import AuditLog


def create_audit_log(
    session: Session,
    user_id: str,
    operation: str,
    entity_type: str,
    entity_id: str,
    changes: Optional[dict] = None,
    result: str = "success",
    error_message: Optional[str] = None
) -> AuditLog:
    """Create an immutable audit log entry.
    
    Args:
        session: Database session
        user_id: ID of user performing the operation
        operation: Operation type (CREATE, UPDATE, DELETE)
        entity_type: Type of entity (ToolItem, ToolAssembly, etc.)
        entity_id: ID of the entity
        changes: Optional dict of changes (before/after values)
        result: Result of operation (success, error)
        error_message: Optional error message if result is error
        
    Returns:
        AuditLog: Created audit log entry
        
    Raises:
        ValueError: If required fields are missing
        
    Assumptions:
    - Audit logs are immutable once created
    - Timestamp auto-generated
    - All operations logged regardless of success/failure
    """
    if not user_id:
        raise ValueError("user_id is required")
    if not operation:
        raise ValueError("operation is required")
    if not entity_type:
        raise ValueError("entity_type is required")
    if not entity_id:
        raise ValueError("entity_id is required")
    
    audit_log = AuditLog(
        id=str(uuid4()),
        user_id=user_id,
        timestamp=datetime.now(UTC),
        operation=operation,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=changes,
        result=result,
        error_message=error_message
    )
    
    session.add(audit_log)
    session.commit()
    
    return audit_log


def get_audit_logs_by_user(
    session: Session,
    user_id: str,
    limit: int = 100,
    offset: int = 0
) -> List[AuditLog]:
    """Query audit logs by user.
    
    Args:
        session: Database session
        user_id: User ID to filter by
        limit: Maximum number of logs to return
        offset: Number of logs to skip
        
    Returns:
        List[AuditLog]: List of audit logs for the user
        
    Assumptions:
    - Ordered by timestamp descending (newest first)
    - Used for user activity reports
    """
    return session.query(AuditLog).filter(
        AuditLog.user_id == user_id
    ).order_by(
        AuditLog.timestamp.desc()
    ).limit(limit).offset(offset).all()


def get_audit_logs_by_entity(
    session: Session,
    entity_type: str,
    entity_id: str,
    limit: int = 100,
    offset: int = 0
) -> List[AuditLog]:
    """Query audit logs by entity.
    
    Args:
        session: Database session
        entity_type: Type of entity
        entity_id: ID of entity
        limit: Maximum number of logs to return
        offset: Number of logs to skip
        
    Returns:
        List[AuditLog]: List of audit logs for the entity
        
    Assumptions:
    - Ordered by timestamp ascending (chronological history)
    - Used for entity change history
    """
    return session.query(AuditLog).filter(
        AuditLog.entity_type == entity_type,
        AuditLog.entity_id == entity_id
    ).order_by(
        AuditLog.timestamp.asc()
    ).limit(limit).offset(offset).all()


def log_bulk_operation(
    session: Session,
    user_id: str,
    operation: str,
    entity_type: str,
    results: List[dict],
    errors: List[dict]
) -> None:
    """Log a bulk operation with multiple entities.
    
    Args:
        session: Database session
        user_id: User performing operation
        operation: Operation type (CREATE, UPDATE, DELETE)
        entity_type: Type of entities
        results: List of successful results with entity_id
        errors: List of errors with entity_id if available
        
    Assumptions:
    - Creates one audit log entry per entity
    - Handles both successes and failures
    - Used by bulk API endpoints
    """
    # Log successful operations
    for result in results:
        entity_id = result.get("id")
        if entity_id:
            create_audit_log(
                session=session,
                user_id=user_id,
                operation=operation,
                entity_type=entity_type,
                entity_id=entity_id,
                changes=result.get("changes"),
                result="success"
            )
    
    # Log failed operations
    for error in errors:
        entity_id = error.get("id", "unknown")
        create_audit_log(
            session=session,
            user_id=user_id,
            operation=operation,
            entity_type=entity_type,
            entity_id=entity_id,
            result="error",
            error_message=error.get("message", "Unknown error")
        )
