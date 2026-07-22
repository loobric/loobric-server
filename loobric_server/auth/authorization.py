# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Authorization and permission checking functions.

Implements scope-based authorization, data isolation, and permission helpers.

Assumptions:
- Scopes follow pattern: "read", "write:<entity>", "delete:<entity>", "admin:<entity>"
- Wildcards supported: "admin:*" grants all permissions, "write:*" grants write to all
- Users can only access their own data unless admin
- Authorization decisions are logged for audit trail
"""
import structlog
from typing import Optional

logger = structlog.get_logger()


class PermissionDeniedError(Exception):
    """Raised when user lacks required permission."""
    pass


def has_scope(scopes: list[str], required_scope: str) -> bool:
    """Check if user has required scope.
    
    Args:
        scopes: List of scopes granted to user
        required_scope: Required scope (e.g., "read", "write:items")
        
    Returns:
        bool: True if user has required scope, False otherwise
        
    Assumptions:
    - Exact match grants permission
    - "admin:*" grants all permissions
    - Wildcard entity matching (e.g., "write:*" matches "write:items")
    - Case-sensitive matching
    """
    if not scopes:
        return False
    
    # Check exact match
    if required_scope in scopes:
        return True
    
    # Check for admin wildcard (grants everything)
    if "admin:*" in scopes:
        return True
    
    # Check for action wildcard (e.g., "write:*" matches "write:items")
    if ":" in required_scope:
        action, entity = required_scope.split(":", 1)
        wildcard_scope = f"{action}:*"
        if wildcard_scope in scopes:
            return True
    
    # Check if user has "read" scope (covers all read operations)
    if required_scope == "read" and "read" in scopes:
        return True
    
    return False


def require_scope(scopes: list[str], required_scope: str) -> None:
    """Require user to have specific scope, raise if not.
    
    Args:
        scopes: List of scopes granted to user
        required_scope: Required scope
        
    Raises:
        PermissionDeniedError: If user lacks required scope
        
    Assumptions:
    - Raises exception instead of returning boolean
    - Used in API endpoints for enforcement
    """
    if not has_scope(scopes, required_scope):
        raise PermissionDeniedError(
            f"Permission denied: required scope '{required_scope}' not granted"
        )


def check_resource_ownership(
    user_id: str,
    resource_owner_id: str,
    is_admin: bool = False
) -> bool:
    """Check if user can access a resource.
    
    Args:
        user_id: ID of user attempting access
        resource_owner_id: ID of user who owns the resource
        is_admin: Whether the accessing user is an admin
        
    Returns:
        bool: True if access allowed, False otherwise
        
    Assumptions:
    - Users can access their own resources
    - Admins can access all resources
    - Multi-tenant data isolation
    """
    if is_admin:
        return True
    
    return user_id == resource_owner_id


def require_resource_ownership(
    user_id: str,
    resource_owner_id: str,
    is_admin: bool = False
) -> None:
    """Require user to own resource, raise if not.
    
    Args:
        user_id: ID of user attempting access
        resource_owner_id: ID of user who owns the resource
        is_admin: Whether the accessing user is an admin
        
    Raises:
        PermissionDeniedError: If user doesn't own resource and isn't admin
        
    Assumptions:
    - Used for update/delete operations
    - Enforces data isolation
    """
    if not check_resource_ownership(user_id, resource_owner_id, is_admin):
        raise PermissionDeniedError(
            f"User not authorized to access resource owned by {resource_owner_id}"
        )


def should_filter_by_user(is_admin: bool) -> bool:
    """Check if queries should be filtered by user_id.
    
    Args:
        is_admin: Whether the user is an admin
        
    Returns:
        bool: True if queries should be filtered, False otherwise
        
    Assumptions:
    - Regular users only see their own data
    - Admins see all data
    """
    return not is_admin


def get_authorization_context(user, scopes: list[str]) -> dict:
    """Create authorization context dict from user and scopes.
    
    Args:
        user: User object
        scopes: List of scopes
        
    Returns:
        dict: Authorization context with user_id, is_admin, scopes, email
        
    Assumptions:
    - Used for passing auth context through application
    - Standardized format for all endpoints
    """
    return {
        "user_id": user.id,
        "is_admin": user.is_admin,
        "scopes": scopes,
        "email": user.email
    }


def log_authorization_decision(
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    granted: bool,
    reason: str
) -> None:
    """Log an authorization decision for audit trail.
    
    Args:
        user_id: ID of user attempting action
        action: Action attempted (e.g., "write:items", "delete:presets")
        resource_type: Type of resource (e.g., "tool_items")
        resource_id: ID of specific resource
        granted: Whether access was granted
        reason: Human-readable reason for decision
        
    Assumptions:
    - Uses structured logging
    - Logs go to audit system
    - Critical for compliance and debugging
    """
    logger.info(
        "authorization_decision",
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        granted=granted,
        reason=reason
    )


def check_machine_access(
    machine_restriction: Optional[str],
    requested_machine: str
) -> bool:
    """Check if API key can access requested machine.
    
    Args:
        machine_restriction: Machine ID restriction from API key (None if unrestricted)
        requested_machine: Machine ID being accessed
        
    Returns:
        bool: True if access allowed, False otherwise
        
    Assumptions:
    - None restriction means access to all machines
    - Specific restriction limits to that machine only
    """
    if machine_restriction is None:
        return True
    
    return machine_restriction == requested_machine


def require_machine_access(
    machine_restriction: Optional[str],
    requested_machine: str
) -> None:
    """Require API key to have access to requested machine.
    
    Args:
        machine_restriction: Machine ID restriction from API key
        requested_machine: Machine ID being accessed
        
    Raises:
        PermissionDeniedError: If key doesn't have access to machine
        
    Assumptions:
    - Used for machine-specific API key enforcement
    - Prevents cross-machine access
    """
    if not check_machine_access(machine_restriction, requested_machine):
        raise PermissionDeniedError(
            f"API key not authorized for machine '{requested_machine}'"
        )


def check_tag_access(
    api_key_tags: list[str],
    resource_tags: list[str]
) -> bool:
    """Check if API key has access to a resource based on tags.
    
    Args:
        api_key_tags: List of tags from the API key
        resource_tags: List of tags from the resource
        
    Returns:
        bool: True if access is allowed, False otherwise
        
    Assumptions:
    - Empty api_key_tags means no tag-based restrictions
    - Empty resource tags means resource is accessible to all keys with required scopes
    - Access is granted if any tag in api_key_tags matches any tag in resource_tags
    """
    if not api_key_tags:
        return True  # No tag restrictions on the API key
        
    if not resource_tags:
        return True  # Resource has no tags, accessible to all with required scopes
        
    # Check for any matching tags
    return any(tag in resource_tags for tag in api_key_tags)


def require_tag_access(
    api_key_tags: list[str],
    resource_tags: list[str],
    resource_type: str,
    resource_id: str
) -> None:
    """Require API key to have access to resource based on tags.
    
    Args:
        api_key_tags: List of tags from the API key
        resource_tags: List of tags from the resource
        resource_type: Type of resource (for error message)
        resource_id: ID of the resource (for error message)
        
    Raises:
        PermissionDeniedError: If key doesn't have access to resource
    """
    if not check_tag_access(api_key_tags, resource_tags):
        raise PermissionDeniedError(
            f"API key not authorized to access {resource_type} {resource_id} - "
            f"required tags not present in API key"
        )


def check_tag_scope_access(
    scopes: list[str],
    api_key_tags: list[str],
    resource_tags: list[str],
    resource_type: str
) -> bool:
    """Check if user has access based on scopes and tags.
    
    Args:
        scopes: List of scopes granted to user
        api_key_tags: List of tags from the API key
        resource_tags: List of tags from the resource
        resource_type: Type of resource being accessed
        
    Returns:
        bool: True if access is allowed, False otherwise
        
    Assumptions:
    - Users with 'admin:*' scope bypass tag checks
    - Users with 'read' scope can read all resources (subject to tag checks)
    - Users with 'read:all' or 'write:all' bypass tag checks for those operations
    - Otherwise, tag access is checked
    """
    # Admin users bypass all tag checks
    if has_scope(scopes, "admin:*"):
        return True
    
    # Users with read:all or write:all bypass tag checks
    if has_scope(scopes, "read:all") or has_scope(scopes, "write:all"):
        return True
    
    # Check tag-based access (if user has appropriate scope)
    # The 'read' scope grants read access to all resources, subject to tag filtering
    return check_tag_access(api_key_tags, resource_tags)


def require_tag_scope_access(
    scopes: list[str],
    api_key_tags: list[str],
    resource_tags: list[str],
    resource_type: str,
    resource_id: str,
    action: str = "access"
) -> None:
    """Require user to have access based on scopes and tags.
    
    Args:
        scopes: List of scopes granted to user
        api_key_tags: List of tags from the API key
        resource_tags: List of tags from the resource
        resource_type: Type of resource being accessed
        resource_id: ID of the resource (for error message)
        action: Action being performed (for error message)
        
    Raises:
        PermissionDeniedError: If access is denied
    """
    if not check_tag_scope_access(scopes, api_key_tags, resource_tags, resource_type):
        raise PermissionDeniedError(
            f"Not authorized to {action} {resource_type} {resource_id} - "
            f"missing required tags or scopes"
        )
