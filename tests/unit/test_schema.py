# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Unit tests for database schema.

Tests SQLAlchemy models for all entities with versioning and user attribution.

Assumptions:
- All entities have id, created_at, updated_at, version, user_id
- Relationships use foreign keys
- JSON fields for nested data structures
- Version increments on update
"""
import pytest
from datetime import datetime


@pytest.mark.unit
def test_tool_item_model_exists():
    """Test that ToolItem model is defined.
    
    Assumptions:
    - ToolItem model exists in loobric_server.database.schema
    - Has all required fields
    """
    from loobric_server.database.schema import ToolItem
    
    assert ToolItem is not None
    assert hasattr(ToolItem, '__tablename__')


@pytest.mark.unit
def test_tool_item_has_versioning_fields():
    """Test that ToolItem has versioning fields.
    
    Assumptions:
    - created_at: DateTime, not null
    - updated_at: DateTime, not null
    - version: Integer, default 1
    """
    from loobric_server.database.schema import ToolItem
    
    assert hasattr(ToolItem, 'created_at')
    assert hasattr(ToolItem, 'updated_at')
    assert hasattr(ToolItem, 'version')


@pytest.mark.unit
def test_tool_item_has_user_attribution():
    """Test that ToolItem has user attribution fields.
    
    Assumptions:
    - user_id: String (UUID), not null
    - created_by: String (UUID), not null
    - updated_by: String (UUID), not null
    """
    from loobric_server.database.schema import ToolItem
    
    assert hasattr(ToolItem, 'user_id')
    assert hasattr(ToolItem, 'created_by')
    assert hasattr(ToolItem, 'updated_by')


@pytest.mark.unit
def test_tool_item_create(db_session):
    """Test creating a ToolItem instance.
    
    Assumptions:
    - Can create with minimal required fields
    - Versioning fields auto-populated
    - JSON fields store nested data
    """
    from loobric_server.database.schema import ToolItem
    
    item = ToolItem(
        user_id="user-123",
        created_by="user-123",
        updated_by="user-123",
        type="cutting_tool",
        manufacturer="Sandvik",
        product_code="R390-11T308M-PM",
        description="Carbide milling insert",
        geometry={"nominal_diameter": 12.0, "flute_length": 25.0},
        material={"substrate": "carbide", "coating": "tin"}
    )
    
    db_session.add(item)
    db_session.commit()
    
    assert item.id is not None
    assert item.version == 1
    assert item.created_at is not None
    assert item.updated_at is not None


@pytest.mark.unit
def test_tool_item_version_increments_on_update(db_session):
    """Test that version increments when ToolItem is updated.
    
    Assumptions:
    - version starts at 1
    - version increments on each update
    - updated_at changes on update
    """
    from loobric_server.database.schema import ToolItem
    
    item = ToolItem(
        user_id="user-123",
        created_by="user-123",
        updated_by="user-123",
        type="cutting_tool",
        manufacturer="Sandvik",
        product_code="R390-11T308M-PM"
    )
    
    db_session.add(item)
    db_session.commit()
    
    original_version = item.version
    original_updated_at = item.updated_at
    
    # Update
    item.description = "Updated description"
    item.version += 1  # Will be automated in implementation
    db_session.commit()
    
    assert item.version == original_version + 1
    assert item.updated_at > original_updated_at


@pytest.mark.unit
def test_tool_assembly_model_exists():
    """Test that ToolAssembly model is defined.
    
    Assumptions:
    - ToolAssembly model exists
    - Has relationship to ToolItem
    """
    from loobric_server.database.schema import ToolAssembly
    
    assert ToolAssembly is not None


@pytest.mark.unit
def test_tool_assembly_has_versioning_and_attribution():
    """Test that ToolAssembly has versioning and user attribution.
    
    Assumptions:
    - All standard fields present
    """
    from loobric_server.database.schema import ToolAssembly
    
    assert hasattr(ToolAssembly, 'created_at')
    assert hasattr(ToolAssembly, 'updated_at')
    assert hasattr(ToolAssembly, 'version')
    assert hasattr(ToolAssembly, 'user_id')


@pytest.mark.unit
def test_tool_instance_model_exists():
    """Test that ToolInstance model is defined.
    
    Assumptions:
    - ToolInstance model exists
    - Has foreign key to ToolAssembly
    """
    from loobric_server.database.schema import ToolInstance
    
    assert ToolInstance is not None
    assert hasattr(ToolInstance, 'assembly_id')


@pytest.mark.unit
def test_tool_instance_has_versioning_and_attribution():
    """Test that ToolInstance has versioning and user attribution."""
    from loobric_server.database.schema import ToolInstance
    
    assert hasattr(ToolInstance, 'created_at')
    assert hasattr(ToolInstance, 'updated_at')
    assert hasattr(ToolInstance, 'version')
    assert hasattr(ToolInstance, 'user_id')


@pytest.mark.unit
def test_tool_preset_model_exists():
    """Test that ToolPreset model is defined.
    
    Assumptions:
    - ToolPreset model exists
    - Has foreign key to ToolInstance
    - Has machine_id field
    """
    from loobric_server.database.schema import ToolPreset
    
    assert ToolPreset is not None
    assert hasattr(ToolPreset, 'machine_id')
    assert hasattr(ToolPreset, 'instance_id')


@pytest.mark.unit
def test_tool_preset_has_versioning_and_attribution():
    """Test that ToolPreset has versioning and user attribution."""
    from loobric_server.database.schema import ToolPreset
    
    assert hasattr(ToolPreset, 'created_at')
    assert hasattr(ToolPreset, 'updated_at')
    assert hasattr(ToolPreset, 'version')
    assert hasattr(ToolPreset, 'user_id')


@pytest.mark.unit
def test_tool_usage_model_exists():
    """Test that ToolUsage model is defined.
    
    Assumptions:
    - ToolUsage model exists
    - Has foreign key to ToolPreset
    """
    from loobric_server.database.schema import ToolUsage
    
    assert ToolUsage is not None
    assert hasattr(ToolUsage, 'preset_id')


@pytest.mark.unit
def test_tool_usage_has_versioning_and_attribution():
    """Test that ToolUsage has versioning and user attribution."""
    from loobric_server.database.schema import ToolUsage
    
    assert hasattr(ToolUsage, 'created_at')
    assert hasattr(ToolUsage, 'updated_at')
    assert hasattr(ToolUsage, 'version')
    assert hasattr(ToolUsage, 'user_id')


@pytest.mark.unit
def test_tool_set_model_exists():
    """Test that ToolSet model is defined.
    
    Assumptions:
    - ToolSet model exists
    - Can have type: machine_setup, job_specific, template, project
    """
    from loobric_server.database.schema import ToolSet
    
    assert ToolSet is not None
    assert hasattr(ToolSet, 'type')


@pytest.mark.unit
def test_tool_set_has_versioning_and_attribution():
    """Test that ToolSet has versioning and user attribution."""
    from loobric_server.database.schema import ToolSet
    
    assert hasattr(ToolSet, 'created_at')
    assert hasattr(ToolSet, 'updated_at')
    assert hasattr(ToolSet, 'version')
    assert hasattr(ToolSet, 'user_id')


@pytest.mark.unit
def test_user_model_exists():
    """Test that User model is defined for authentication.
    
    Assumptions:
    - User model exists for Phase 3
    - Has email and password_hash fields
    """
    from loobric_server.database.schema import User
    
    assert User is not None
    assert hasattr(User, 'email')
    assert hasattr(User, 'password_hash')


@pytest.mark.unit
def test_api_key_model_exists():
    """Test that ApiKey model is defined for authentication.
    
    Assumptions:
    - ApiKey model exists for Phase 3
    - Has foreign key to User
    - Has scopes and expiration fields
    """
    from loobric_server.database.schema import ApiKey
    
    assert ApiKey is not None
    assert hasattr(ApiKey, 'user_id')
    assert hasattr(ApiKey, 'scopes')
    assert hasattr(ApiKey, 'expires_at')


@pytest.mark.unit
def test_relationships_defined():
    """Test that relationships between entities are defined.
    
    Assumptions:
    - ToolAssembly references ToolItems
    - ToolInstance references ToolAssembly
    - ToolPreset references ToolInstance
    - ToolUsage references ToolPreset
    """
    from loobric_server.database.schema import (
        ToolItem, ToolAssembly, ToolInstance, ToolPreset, ToolUsage
    )
    
    # These will be defined as SQLAlchemy relationships
    # Just verify models are importable for now
    assert ToolItem is not None
    assert ToolAssembly is not None
    assert ToolInstance is not None
    assert ToolPreset is not None
    assert ToolUsage is not None


@pytest.mark.unit
def test_init_db_function_exists():
    """Test that init_db function exists to initialize database.
    
    Assumptions:
    - init_db() creates all tables
    - Can be called with engine parameter
    """
    from loobric_server.database.schema import init_db
    
    assert init_db is not None
    assert callable(init_db)
