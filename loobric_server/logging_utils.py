# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Logging utilities for Loobric.

Provides specialized logging functions for:
- Application logs (operational)
- Audit logs (compliance)
- Security logs (forensics)

Assumptions:
- All logs use structlog for structured output
- Sensitive data (passwords, API keys) are never logged
- Audit logs are immutable and retained for 7 years
"""
from typing import Any, Dict, Optional

from loobric_server.logging_config import get_logger

# Get loggers for different categories
app_logger = get_logger("loobric_server.application")
audit_logger = get_logger("loobric_server.audit")
security_logger = get_logger("loobric_server.security")


def log_application_event(
    event: str,
    **kwargs: Any
) -> None:
    """Log an application operational event.
    
    Args:
        event: Event name (e.g., "api_request", "database_query")
        **kwargs: Additional context (method, path, status_code, etc.)
        
    Assumptions:
    - Used for operational logging
    - Includes API requests, database operations, background jobs
    - Not used for compliance or security events
    """
    app_logger.info(event, **kwargs)


def log_audit_event(
    user_id: str,
    operation: str,
    entity_type: str,
    entity_id: str,
    changes: Optional[Dict[str, Any]] = None,
    **kwargs: Any
) -> None:
    """Log an audit event for compliance.
    
    Args:
        user_id: User who performed the operation
        operation: Operation type (create, update, delete)
        entity_type: Type of entity (ToolItem, ToolAssembly, etc.)
        entity_id: ID of the entity
        changes: Dictionary of changes made
        **kwargs: Additional context
        
    Assumptions:
    - All data modifications must be logged
    - Audit logs are immutable
    - Sensitive data is sanitized before logging
    - Retention: 7 years for compliance
    """
    # Sanitize changes to remove sensitive data
    sanitized_changes = _sanitize_data(changes) if changes else None
    
    audit_logger.info(
        "audit_event",
        user_id=user_id,
        operation=operation,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=sanitized_changes,
        **kwargs
    )


def log_security_event(
    event: str,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    reason: Optional[str] = None,
    **kwargs: Any
) -> None:
    """Log a security event for forensics.
    
    Args:
        event: Security event type (authentication_failed, permission_denied, etc.)
        user_id: User involved (if known)
        ip_address: IP address of request
        reason: Reason for security event
        **kwargs: Additional context
        
    Assumptions:
    - Used for failed authentication, permission denials, rate limits
    - Helps detect suspicious activity
    - Retention: Same as application logs (30 days)
    """
    security_logger.warning(
        event,
        user_id=user_id,
        ip_address=ip_address,
        reason=reason,
        **kwargs
    )


def _sanitize_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize sensitive data from log entries.
    
    Args:
        data: Dictionary that may contain sensitive data
        
    Returns:
        Dict: Sanitized dictionary with sensitive fields removed/redacted
        
    Assumptions:
    - Passwords never logged
    - API keys never logged (only key_id if present)
    - Other sensitive fields can be added to SENSITIVE_FIELDS
    """
    SENSITIVE_FIELDS = {"password", "api_key", "secret", "token"}
    
    if not data:
        return data
    
    sanitized = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_FIELDS:
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_data(value)
        elif isinstance(value, list):
            sanitized[key] = [
                _sanitize_data(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            sanitized[key] = value
    
    return sanitized
