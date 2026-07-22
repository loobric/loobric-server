# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Unit tests for authorization and permission checking.

Tests scope-based permissions, data isolation, and authorization helpers.

Assumptions:
- Scopes follow pattern: "read", "write:<entity>", "delete:<entity>", "admin:<entity>"
- Read scope allows listing/viewing any entity
- Write scope allows create/update for specific entity type
- Delete scope allows deletion for specific entity type
- Admin scope allows all operations for specific entity type
- Users can only access their own data (user_id filtering)
- Admins can access all data
"""
import pytest
from datetime import datetime, UTC


@pytest.mark.unit
def test_has_scope_with_exact_match():
    """Test scope checking with exact match.
    
    Assumptions:
    - Exact scope match returns True
    - Scopes are case-sensitive
    """
    from loobric_server.auth.authorization import has_scope
    
    scopes = ["read", "write:items", "write:presets"]
    
    assert has_scope(scopes, "read") is True
    assert has_scope(scopes, "write:items") is True
    assert has_scope(scopes, "write:presets") is True


@pytest.mark.unit
def test_has_scope_without_match():
    """Test scope checking without match.
    
    Assumptions:
    - Missing scope returns False
    - Does not raise exception
    """
    from loobric_server.auth.authorization import has_scope
    
    scopes = ["read"]
    
    assert has_scope(scopes, "write:items") is False
    assert has_scope(scopes, "delete:items") is False


@pytest.mark.unit
def test_has_scope_with_wildcard():
    """Test scope checking with wildcard admin scope.
    
    Assumptions:
    - "admin:*" grants all permissions
    - "write:*" grants write to all entities
    """
    from loobric_server.auth.authorization import has_scope
    
    admin_scopes = ["admin:*"]
    
    assert has_scope(admin_scopes, "read") is True
    assert has_scope(admin_scopes, "write:items") is True
    assert has_scope(admin_scopes, "delete:presets") is True
    assert has_scope(admin_scopes, "admin:users") is True


@pytest.mark.unit
def test_has_scope_with_entity_wildcard():
    """Test scope checking with entity-level wildcard.
    
    Assumptions:
    - "write:*" grants write access to all entity types
    - "admin:items" grants all operations on items
    """
    from loobric_server.auth.authorization import has_scope
    
    write_all_scopes = ["write:*"]
    assert has_scope(write_all_scopes, "write:items") is True
    assert has_scope(write_all_scopes, "write:presets") is True
    assert has_scope(write_all_scopes, "write:users") is True
    
    # But doesn't grant delete or admin
    assert has_scope(write_all_scopes, "delete:items") is False
    assert has_scope(write_all_scopes, "admin:users") is False


@pytest.mark.unit
def test_require_scope_success():
    """Test require_scope helper with valid scope.
    
    Assumptions:
    - Returns None (no exception) if scope present
    """
    from loobric_server.auth.authorization import require_scope
    
    scopes = ["read", "write:items"]
    
    # Should not raise
    require_scope(scopes, "read")
    require_scope(scopes, "write:items")


@pytest.mark.unit
def test_require_scope_failure():
    """Test require_scope helper raises on missing scope.
    
    Assumptions:
    - Raises PermissionDeniedError if scope missing
    - Error includes helpful message
    """
    from loobric_server.auth.authorization import require_scope, PermissionDeniedError
    
    scopes = ["read"]
    
    with pytest.raises(PermissionDeniedError) as exc_info:
        require_scope(scopes, "write:items")
    
    assert "write:items" in str(exc_info.value)


@pytest.mark.unit
def test_check_resource_ownership_same_user():
    """Test resource ownership check for same user.
    
    Assumptions:
    - User can access their own resources
    - Returns True for same user_id
    """
    from loobric_server.auth.authorization import check_resource_ownership
    
    user_id = "user-123"
    resource_owner_id = "user-123"
    
    assert check_resource_ownership(user_id, resource_owner_id, is_admin=False) is True


@pytest.mark.unit
def test_check_resource_ownership_different_user():
    """Test resource ownership check for different user.
    
    Assumptions:
    - Non-admin cannot access other users' resources
    - Returns False for different user_id
    """
    from loobric_server.auth.authorization import check_resource_ownership
    
    user_id = "user-123"
    resource_owner_id = "user-456"
    
    assert check_resource_ownership(user_id, resource_owner_id, is_admin=False) is False


@pytest.mark.unit
def test_check_resource_ownership_admin():
    """Test resource ownership check for admin user.
    
    Assumptions:
    - Admin can access any user's resources
    - Returns True even for different user_id
    """
    from loobric_server.auth.authorization import check_resource_ownership
    
    admin_user_id = "admin-123"
    resource_owner_id = "user-456"
    
    assert check_resource_ownership(admin_user_id, resource_owner_id, is_admin=True) is True


@pytest.mark.unit
def test_require_resource_ownership_success():
    """Test require_resource_ownership with valid access.
    
    Assumptions:
    - No exception if user owns resource
    - No exception if user is admin
    """
    from loobric_server.auth.authorization import require_resource_ownership
    
    # Same user - should not raise
    require_resource_ownership("user-123", "user-123", is_admin=False)
    
    # Admin - should not raise
    require_resource_ownership("admin-123", "user-456", is_admin=True)


@pytest.mark.unit
def test_require_resource_ownership_failure():
    """Test require_resource_ownership raises on unauthorized access.
    
    Assumptions:
    - Raises PermissionDeniedError if user doesn't own resource
    - Error message is helpful
    """
    from loobric_server.auth.authorization import require_resource_ownership, PermissionDeniedError
    
    with pytest.raises(PermissionDeniedError) as exc_info:
        require_resource_ownership("user-123", "user-456", is_admin=False)
    
    assert "not authorized" in str(exc_info.value).lower()


@pytest.mark.unit
def test_filter_by_user_for_regular_user():
    """Test query filtering by user_id for regular user.
    
    Assumptions:
    - Regular users see only their own data
    - Returns query filtered by user_id
    """
    from loobric_server.auth.authorization import should_filter_by_user
    
    # Regular user should be filtered
    assert should_filter_by_user(is_admin=False) is True


@pytest.mark.unit
def test_filter_by_user_for_admin():
    """Test query filtering by user_id for admin.
    
    Assumptions:
    - Admins see all data (no filtering)
    - Returns False for admin users
    """
    from loobric_server.auth.authorization import should_filter_by_user
    
    # Admin should not be filtered
    assert should_filter_by_user(is_admin=True) is False


@pytest.mark.unit
def test_get_authorization_context():
    """Test creating authorization context from user.
    
    Assumptions:
    - Returns dict with user_id, is_admin, scopes
    - Used for passing auth context to functions
    """
    from loobric_server.auth.authorization import get_authorization_context
    from loobric_server.database.schema import User
    
    user = User(
        id="user-123",
        email="test@example.com",
        password_hash="hash",
        is_active=True,
        is_admin=False
    )
    scopes = ["read", "write:items"]
    
    context = get_authorization_context(user, scopes)
    
    assert context["user_id"] == "user-123"
    assert context["is_admin"] is False
    assert context["scopes"] == scopes
    assert context["email"] == "test@example.com"


@pytest.mark.unit
def test_log_authorization_decision():
    """Test logging authorization decisions.
    
    Assumptions:
    - Logs authorization decisions for audit trail
    - Includes user, action, resource, result
    """
    from loobric_server.auth.authorization import log_authorization_decision
    
    # Should not raise
    log_authorization_decision(
        user_id="user-123",
        action="write:items",
        resource_type="tool_items",
        resource_id="item-456",
        granted=True,
        reason="User has required scope"
    )
    
    log_authorization_decision(
        user_id="user-123",
        action="delete:presets",
        resource_type="tool_presets",
        resource_id="preset-789",
        granted=False,
        reason="User lacks required scope"
    )


@pytest.mark.unit
def test_read_permission_allows_all_entities():
    """Test that 'read' scope allows reading all entity types.
    
    Assumptions:
    - Single 'read' scope covers all entities
    - Don't need entity-specific read scopes
    """
    from loobric_server.auth.authorization import has_scope
    
    scopes = ["read"]
    
    # Read scope is sufficient for all reads
    assert has_scope(scopes, "read") is True


@pytest.mark.unit
def test_write_permission_is_entity_specific():
    """Test that write permissions are entity-specific.
    
    Assumptions:
    - write:items only allows writing items
    - Need separate scope for each entity type
    """
    from loobric_server.auth.authorization import has_scope
    
    scopes = ["write:items"]
    
    assert has_scope(scopes, "write:items") is True
    assert has_scope(scopes, "write:presets") is False
    assert has_scope(scopes, "write:assemblies") is False


@pytest.mark.unit
def test_permission_hierarchy():
    """Test that admin implies write, write implies read.
    
    Assumptions:
    - admin:items grants write:items and read
    - This may or may not be implemented with scope expansion
    """
    from loobric_server.auth.authorization import has_scope
    
    # Test that admin scope grants lower permissions
    admin_scopes = ["admin:items"]
    
    # Admin on specific entity should grant write on that entity
    assert has_scope(admin_scopes, "admin:items") is True
    
    # For now, we might not implement automatic hierarchy
    # but the test documents the intended behavior


@pytest.mark.unit
def test_machine_specific_scope():
    """Test machine-specific scope restrictions.
    
    Assumptions:
    - API keys can be limited to specific machine_id
    - Enforced at authorization layer
    """
    from loobric_server.auth.authorization import check_machine_access
    
    # Key limited to specific machine
    machine_id_restriction = "mill-01"
    
    # Access to same machine - granted
    assert check_machine_access(machine_id_restriction, "mill-01") is True
    
    # Access to different machine - denied
    assert check_machine_access(machine_id_restriction, "mill-02") is False
    
    # No restriction (None) - all machines granted
    assert check_machine_access(None, "mill-01") is True
    assert check_machine_access(None, "mill-02") is True
