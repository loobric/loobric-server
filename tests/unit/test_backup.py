# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Unit tests for backup and restore operations.

Tests full database export/import with validation and atomic operations.

Assumptions:
- Backup format is JSON
- All data serializable (datetimes as ISO strings)
- Atomic restore (all or nothing)
- Validates schema version compatibility
- Preserves versioning fields (created_at, updated_at, version)
- Preserves user attribution
"""
import pytest
import json
from datetime import datetime, UTC


@pytest.mark.unit
def test_export_empty_database(db_session):
    """Test exporting an empty database.
    
    Assumptions:
    - Returns valid JSON structure
    - Contains metadata (version, timestamp, entity counts)
    - Empty arrays for each entity type
    """
    from loobric_server.backup import export_backup
    
    backup = export_backup(db_session)
    
    assert isinstance(backup, dict)
    assert "metadata" in backup
    assert "version" in backup["metadata"]
    assert "timestamp" in backup["metadata"]
    assert "entities" in backup
    
    # Should have arrays for each entity type (v2 sectioned records)
    expected_entities = {
        "users",
        "machine_records",
        "tool_catalog_records",
        "tool_instance_records",
        "tool_table_entry_records",
        "tool_set_records",
        "entry_proposals",
        "api_keys",
    }
    assert set(backup["entities"].keys()) == expected_entities
    assert isinstance(backup["entities"]["users"], list)


@pytest.mark.unit
def test_export_with_user_data(db_session):
    """Test exporting database with user data.
    
    Assumptions:
    - Serializes all user fields
    - Password hashes are included (for restore)
    - Datetime fields serialized as ISO strings
    """
    from loobric_server.auth.user import create_user
    from loobric_server.backup import export_backup
    
    user = create_user(
        session=db_session,
        email="test@example.com",
        password="Password123"
    )
    
    backup = export_backup(db_session)
    
    assert len(backup["entities"]["users"]) == 1
    user_data = backup["entities"]["users"][0]
    
    assert user_data["email"] == "test@example.com"
    assert "password_hash" in user_data
    assert "id" in user_data
    assert "created_at" in user_data
    assert "version" in user_data
    assert user_data["is_active"] is True


@pytest.mark.unit
def test_export_with_api_keys(db_session):
    """Test exporting database with API keys.
    
    Assumptions:
    - Includes API key hashes
    - Includes scopes as JSON array
    - Preserves relationships (user_id)
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    from loobric_server.backup import export_backup
    
    user = create_user(db_session, "test@example.com", "Password123")
    create_api_key(
        session=db_session,
        user_id=user.id,
        name="Test Key",
        scopes=["read", "write:items"]
    )
    
    backup = export_backup(db_session)
    
    assert len(backup["entities"]["api_keys"]) == 1
    key_data = backup["entities"]["api_keys"][0]
    
    assert key_data["name"] == "Test Key"
    assert key_data["scopes"] == ["read", "write:items"]
    assert key_data["user_id"] == user.id


@pytest.mark.unit
def test_export_preserves_version_fields(db_session):
    """Test that export preserves versioning fields.
    
    Assumptions:
    - created_at, updated_at, version all included
    - Timestamps are ISO format strings
    """
    from loobric_server.auth.user import create_user
    from loobric_server.backup import export_backup
    
    user = create_user(db_session, "test@example.com", "Password123")
    
    backup = export_backup(db_session)
    user_data = backup["entities"]["users"][0]
    
    assert "created_at" in user_data
    assert "updated_at" in user_data
    assert "version" in user_data
    assert user_data["version"] == 1
    
    # Timestamps should be ISO strings
    datetime.fromisoformat(user_data["created_at"].replace("Z", "+00:00"))


@pytest.mark.unit
def test_backup_to_json_string(db_session):
    """Test exporting backup as JSON string.
    
    Assumptions:
    - Valid JSON format
    - Can be parsed back to dict
    """
    from loobric_server.auth.user import create_user
    from loobric_server.backup import export_backup_json
    
    create_user(db_session, "test@example.com", "Password123")
    
    json_str = export_backup_json(db_session)
    
    assert isinstance(json_str, str)
    
    # Should be parseable
    parsed = json.loads(json_str)
    assert "metadata" in parsed
    assert "entities" in parsed


@pytest.mark.unit
def test_restore_empty_backup(db_session):
    """Test restoring from an empty backup.
    
    Assumptions:
    - Creates no entities
    - Returns success result
    """
    from loobric_server.backup import restore_backup
    
    backup = {
        "metadata": {"version": "0.1.0", "timestamp": datetime.now(UTC).isoformat()},
        "entities": {
            "users": [],
            "api_keys": [],
            "tool_items": []
        }
    }
    
    result = restore_backup(db_session, backup)
    
    assert result["success"] is True
    assert result["restored_count"] == 0


@pytest.mark.unit
def test_restore_user_data(db_session):
    """Test restoring user data from backup.
    
    Assumptions:
    - Recreates users with same IDs
    - Preserves password hashes
    - Preserves timestamps and version
    """
    from loobric_server.auth.user import create_user, get_user_by_email
    from loobric_server.backup import export_backup, restore_backup
    
    # Create user
    original_user = create_user(db_session, "test@example.com", "Password123")
    original_id = original_user.id
    original_hash = original_user.password_hash
    
    # Export
    backup = export_backup(db_session)
    
    # Clear database
    from loobric_server.database.schema import User
    db_session.query(User).delete()
    db_session.commit()
    
    # Restore
    restore_backup(db_session, backup)
    
    # Verify
    restored_user = get_user_by_email(db_session, "test@example.com")
    assert restored_user is not None
    assert restored_user.id == original_id
    assert restored_user.password_hash == original_hash


@pytest.mark.unit
def test_restore_with_relationships(db_session):
    """Test restoring data with foreign key relationships.
    
    Assumptions:
    - Restores in correct order (users before api_keys)
    - Preserves relationships
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key, list_user_api_keys
    from loobric_server.backup import export_backup, restore_backup
    
    # Create data with relationship
    user = create_user(db_session, "test@example.com", "Password123")
    create_api_key(db_session, user.id, "Test Key", ["read"])
    
    # Export
    backup = export_backup(db_session)
    
    # Clear database (simplified for test - would need CASCADE)
    from loobric_server.database.schema import ApiKey, User
    db_session.query(ApiKey).delete()
    db_session.query(User).delete()
    db_session.commit()
    
    # Restore
    restore_backup(db_session, backup)
    
    # Verify relationship
    keys = list_user_api_keys(db_session, user.id)
    assert len(keys) == 1


@pytest.mark.unit
def test_restore_validation_rejects_invalid_version(db_session):
    """Test that restore rejects incompatible backup version.
    
    Assumptions:
    - Checks version compatibility
    - Raises error for incompatible versions
    """
    from loobric_server.backup import restore_backup, BackupVersionError
    
    backup = {
        "metadata": {"version": "99.0.0", "timestamp": datetime.now(UTC).isoformat()},
        "entities": {"users": []}
    }
    
    with pytest.raises(BackupVersionError):
        restore_backup(db_session, backup)


@pytest.mark.unit
def test_restore_validation_rejects_missing_fields(db_session):
    """Test that restore validates required fields.
    
    Assumptions:
    - Validates entity structure
    - Raises error for missing required fields
    """
    from loobric_server.backup import restore_backup, BackupValidationError
    
    backup = {
        "metadata": {"version": "0.1.0", "timestamp": datetime.now(UTC).isoformat()},
        "entities": {
            "users": [
                {"email": "test@example.com"}  # Missing required fields
            ]
        }
    }
    
    with pytest.raises(BackupValidationError):
        restore_backup(db_session, backup)


@pytest.mark.unit
def test_restore_is_atomic(db_session):
    """Test that restore is atomic (all or nothing).
    
    Assumptions:
    - If any entity fails, entire restore is rolled back
    - Database unchanged after failed restore
    """
    from loobric_server.auth.user import create_user, get_user_by_email
    from loobric_server.backup import restore_backup, BackupValidationError
    
    # Create initial user
    create_user(db_session, "existing@example.com", "Password123")
    
    # Backup with one valid and one invalid user
    backup = {
        "metadata": {"version": "0.1.0", "timestamp": datetime.now(UTC).isoformat()},
        "entities": {
            "users": [
                {
                    "id": "valid-id",
                    "email": "valid@example.com",
                    "password_hash": "hash",
                    "is_active": True,
                    "created_at": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                    "version": 1
                },
                {
                    "email": "invalid@example.com"  # Missing required fields
                }
            ]
        }
    }
    
    # Attempt restore (should fail)
    with pytest.raises(BackupValidationError):
        restore_backup(db_session, backup)
    
    # Verify original user still exists and new ones weren't added
    existing = get_user_by_email(db_session, "existing@example.com")
    assert existing is not None
    
    valid_user = get_user_by_email(db_session, "valid@example.com")
    assert valid_user is None  # Should not have been created


@pytest.mark.unit
def test_backup_metadata_includes_counts(db_session):
    """Test that backup metadata includes entity counts.
    
    Assumptions:
    - Metadata includes count for each entity type
    - Useful for verification before restore
    """
    from loobric_server.auth.user import create_user
    from loobric_server.backup import export_backup
    
    create_user(db_session, "user1@example.com", "Password123")
    create_user(db_session, "user2@example.com", "Password123")
    
    backup = export_backup(db_session)
    
    assert "counts" in backup["metadata"]
    assert backup["metadata"]["counts"]["users"] == 2


@pytest.mark.unit
def test_export_excludes_password_reset_tokens(db_session):
    """Test that export excludes temporary data like password reset tokens.
    
    Assumptions:
    - Password reset tokens are temporary, not backed up
    - Other temporary/session data excluded
    """
    from loobric_server.auth.user import create_user, create_password_reset_token
    from loobric_server.backup import export_backup
    
    user = create_user(db_session, "test@example.com", "Password123")
    create_password_reset_token(db_session, user.id)
    
    backup = export_backup(db_session)
    
    # Should not include password reset tokens
    assert "password_reset_tokens" not in backup["entities"] or \
           len(backup["entities"].get("password_reset_tokens", [])) == 0


@pytest.mark.unit
def test_user_level_backup_only_includes_own_data(db_session):
    """Test that user-level backup only includes the user's own data.
    
    Assumptions:
    - Non-admin users can only backup their own tool data
    - Multi-tenant isolation enforced
    - User's own account included, but not other users
    """
    from loobric_server.auth.user import create_user
    from loobric_server.backup import export_backup
    
    # Create two users
    user1 = create_user(db_session, "user1@example.com", "Password123")
    user2 = create_user(db_session, "user2@example.com", "Password123")
    
    # Export backup for user1 only
    backup = export_backup(db_session, user_id=user1.id, admin=False)
    
    # Should only include user1's account
    assert len(backup["entities"]["users"]) == 1
    assert backup["entities"]["users"][0]["id"] == user1.id
    assert backup["entities"]["users"][0]["email"] == "user1@example.com"


@pytest.mark.unit
def test_admin_backup_includes_all_users(db_session):
    """Test that admin-level backup includes all users.
    
    Assumptions:
    - Admin users can backup entire database
    - admin=True parameter includes all data
    """
    from loobric_server.auth.user import create_user
    from loobric_server.backup import export_backup
    
    # Create multiple users
    user1 = create_user(db_session, "user1@example.com", "Password123")
    user2 = create_user(db_session, "user2@example.com", "Password123")
    
    # Export admin backup
    backup = export_backup(db_session, user_id=user1.id, admin=True)
    
    # Should include all users
    assert len(backup["entities"]["users"]) == 2
    user_emails = {u["email"] for u in backup["entities"]["users"]}
    assert "user1@example.com" in user_emails
    assert "user2@example.com" in user_emails


@pytest.mark.unit
def test_user_backup_filters_tool_data_by_user(db_session):
    """Test that user-level backup filters tool entities by user_id.

    Assumptions:
    - Tool entities (v2 sectioned records) have user_id field
    - Only entities owned by user are included
    - Enforces multi-tenant data isolation
    """
    from loobric_server.auth.user import create_user
    from loobric_server.backup import export_backup
    from loobric_server.database.schema import ToolInstanceRecord

    # Create two users
    user1 = create_user(db_session, "user1@example.com", "Password123")
    user2 = create_user(db_session, "user2@example.com", "Password123")

    # Create a v2 sectioned tool instance record for each user
    instance1 = ToolInstanceRecord(
        canonical={"product_code": "USER1-TOOL-001"},
        clients={},
        user_id=user1.id,
        created_by=user1.id,
        updated_by=user1.id
    )
    instance2 = ToolInstanceRecord(
        canonical={"product_code": "USER2-TOOL-001"},
        clients={},
        user_id=user2.id,
        created_by=user2.id,
        updated_by=user2.id
    )
    db_session.add_all([instance1, instance2])
    db_session.commit()

    # Export backup for user1 only
    backup = export_backup(db_session, user_id=user1.id, admin=False)

    # Should only include user1's tool instance records
    assert len(backup["entities"]["tool_instance_records"]) == 1
    record = backup["entities"]["tool_instance_records"][0]
    assert record["canonical"]["product_code"] == "USER1-TOOL-001"
    assert record["user_id"] == user1.id


@pytest.mark.unit
def test_admin_backup_includes_all_tool_data(db_session):
    """Test that admin backup includes all users' tool data.

    Assumptions:
    - Admin backup is not filtered by user_id
    - Includes all tool entities (v2 sectioned records) from all users
    """
    from loobric_server.auth.user import create_user
    from loobric_server.backup import export_backup
    from loobric_server.database.schema import ToolInstanceRecord

    # Create two users
    user1 = create_user(db_session, "user1@example.com", "Password123")
    user2 = create_user(db_session, "user2@example.com", "Password123")

    # Create a v2 sectioned tool instance record for each user
    instance1 = ToolInstanceRecord(
        canonical={"product_code": "USER1-TOOL-001"},
        clients={},
        user_id=user1.id,
        created_by=user1.id,
        updated_by=user1.id
    )
    instance2 = ToolInstanceRecord(
        canonical={"product_code": "USER2-TOOL-001"},
        clients={},
        user_id=user2.id,
        created_by=user2.id,
        updated_by=user2.id
    )
    db_session.add_all([instance1, instance2])
    db_session.commit()

    # Export admin backup
    backup = export_backup(db_session, user_id=user1.id, admin=True)

    # Should include all tool instance records
    assert len(backup["entities"]["tool_instance_records"]) == 2
    tool_codes = {
        record["canonical"]["product_code"]
        for record in backup["entities"]["tool_instance_records"]
    }
    assert "USER1-TOOL-001" in tool_codes
    assert "USER2-TOOL-001" in tool_codes


@pytest.mark.unit
def test_user_backup_includes_own_api_keys_only(db_session):
    """Test that user-level backup includes only their API keys.
    
    Assumptions:
    - API keys are user-specific
    - User backup includes their keys but not others'
    """
    from loobric_server.auth.user import create_user
    from loobric_server.auth.apikey import create_api_key
    from loobric_server.backup import export_backup
    
    # Create two users with API keys
    user1 = create_user(db_session, "user1@example.com", "Password123")
    user2 = create_user(db_session, "user2@example.com", "Password123")
    
    create_api_key(db_session, user1.id, "User1 Key", ["read"])
    create_api_key(db_session, user2.id, "User2 Key", ["read"])
    
    # Export backup for user1
    backup = export_backup(db_session, user_id=user1.id, admin=False)
    
    # Should only include user1's API keys
    assert len(backup["entities"]["api_keys"]) == 1
    assert backup["entities"]["api_keys"][0]["name"] == "User1 Key"
    assert backup["entities"]["api_keys"][0]["user_id"] == user1.id


@pytest.mark.unit
def test_backup_metadata_indicates_backup_type(db_session):
    """Test that backup metadata indicates whether it's user or admin backup.
    
    Assumptions:
    - Metadata includes 'backup_type': 'user' or 'admin'
    - Metadata includes 'user_id' for user backups
    - Helps identify backup scope when restoring
    """
    from loobric_server.auth.user import create_user
    from loobric_server.backup import export_backup
    
    user = create_user(db_session, "test@example.com", "Password123")
    
    # User backup
    user_backup = export_backup(db_session, user_id=user.id, admin=False)
    assert user_backup["metadata"]["backup_type"] == "user"
    assert user_backup["metadata"]["user_id"] == user.id
    
    # Admin backup
    admin_backup = export_backup(db_session, user_id=user.id, admin=True)
    assert admin_backup["metadata"]["backup_type"] == "admin"


# --- Schema-revision stamping & restore drift (migration spine, Phase 2) ---


@pytest.mark.unit
def test_export_stamps_schema_revision(db_session):
    """A backup records the schema revision it was taken on, so it is
    self-describing for restore-time compatibility checks."""
    from loobric_server.backup import export_backup
    from loobric_server.migrations import current_head

    backup = export_backup(db_session)
    assert backup["metadata"]["schema_revision"] == current_head()
    assert backup["metadata"]["schema_revision"] is not None


@pytest.mark.unit
def test_restore_accepts_equal_revision(db_session):
    """Restoring a backup taken on the current schema revision is allowed."""
    from loobric_server.backup import export_backup, restore_backup

    backup = export_backup(db_session)
    result = restore_backup(db_session, backup)
    assert result["success"] is True


@pytest.mark.unit
def test_restore_accepts_older_revision(db_session):
    """An older backup restores into the current schema (newer columns take
    their model defaults)."""
    from loobric_server.backup import export_backup, restore_backup

    backup = export_backup(db_session)
    backup["metadata"]["schema_revision"] = "0000"
    result = restore_backup(db_session, backup)
    assert result["success"] is True


@pytest.mark.unit
def test_restore_accepts_backup_without_schema_revision(db_session):
    """Backups predating this field (no schema_revision) still restore."""
    from loobric_server.backup import export_backup, restore_backup

    backup = export_backup(db_session)
    del backup["metadata"]["schema_revision"]
    result = restore_backup(db_session, backup)
    assert result["success"] is True


@pytest.mark.unit
def test_restore_refuses_newer_revision(db_session):
    """Restoring a backup taken on a NEWER schema than this server understands
    is refused — it would be a downgrade and risk data loss."""
    from loobric_server.backup import export_backup, restore_backup, BackupVersionError

    backup = export_backup(db_session)
    backup["metadata"]["schema_revision"] = "9999"
    with pytest.raises(BackupVersionError, match="newer than"):
        restore_backup(db_session, backup)
