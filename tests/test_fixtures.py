# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Tests for pytest fixtures.

Validates that backup-based fixtures work correctly.

Assumptions:
- Fixtures use backup/restore mechanism
- Sample data is realistic and valid
"""
import pytest


@pytest.mark.unit
def test_minimal_backup_fixture(minimal_backup):
    """Test minimal backup fixture structure.
    
    Assumptions:
    - Contains single user
    - No tool data
    - Admin user
    """
    assert "metadata" in minimal_backup
    assert "entities" in minimal_backup
    assert minimal_backup["metadata"]["backup_type"] == "admin"
    assert len(minimal_backup["entities"]["users"]) == 1
    assert minimal_backup["entities"]["users"][0]["is_admin"] is True
    assert len(minimal_backup["entities"]["tool_instance_records"]) == 0


@pytest.mark.unit
def test_single_user_backup_fixture(single_user_backup):
    """Test single user backup fixture structure.
    
    Assumptions:
    - Contains one user with tool data
    - User has API keys
    - User-level backup type
    """
    assert "metadata" in single_user_backup
    assert "entities" in single_user_backup
    assert single_user_backup["metadata"]["backup_type"] == "user"
    assert len(single_user_backup["entities"]["users"]) == 1
    assert len(single_user_backup["entities"]["api_keys"]) >= 1
    assert len(single_user_backup["entities"]["tool_instance_records"]) >= 1


@pytest.mark.unit
def test_multi_user_backup_fixture(multi_user_backup):
    """Test multi-user backup fixture structure.
    
    Assumptions:
    - Contains multiple users
    - Each user has their own data
    - Admin-level backup type
    """
    assert "metadata" in multi_user_backup
    assert "entities" in multi_user_backup
    assert multi_user_backup["metadata"]["backup_type"] == "admin"
    assert len(multi_user_backup["entities"]["users"]) >= 2
    
    # First user should be admin
    users = multi_user_backup["entities"]["users"]
    assert users[0]["is_admin"] is True
    assert users[1]["is_admin"] is False


@pytest.mark.unit
def test_db_with_sample_data_fixture(db_with_sample_data):
    """Test database fixture pre-loaded with sample data.
    
    Assumptions:
    - Database has been populated via backup restore
    - Contains user and tool items
    """
    from loobric_server.database.schema import User, ToolInstanceRecord, ApiKey

    # Verify data was loaded
    users = db_with_sample_data.query(User).all()
    assert len(users) >= 1

    tool_records = db_with_sample_data.query(ToolInstanceRecord).all()
    assert len(tool_records) >= 1

    api_keys = db_with_sample_data.query(ApiKey).all()
    assert len(api_keys) >= 1


@pytest.mark.unit
def test_fixture_data_consistency(single_user_backup):
    """Test that fixture data is internally consistent.
    
    Assumptions:
    - All API keys reference valid user
    - All tool instance records reference valid user
    """
    user_id = single_user_backup["entities"]["users"][0]["id"]

    # All API keys should belong to this user
    for key in single_user_backup["entities"]["api_keys"]:
        assert key["user_id"] == user_id

    # All tool instance records should belong to this user
    for item in single_user_backup["entities"]["tool_instance_records"]:
        assert item["user_id"] == user_id
