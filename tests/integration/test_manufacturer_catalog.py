# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for manufacturer catalog functionality.

Simplified Schema:
- ManufacturerCatalog: Contains tool_ids array, tags, is_published
- ToolItem: Only needs parent_tool_id (nullable) for catalog references
- Same tool can exist in multiple catalogs

Assumptions:
- Users with role="manufacturer" can create catalogs
- Bulk-first API: Use existing /api/v1/tool-items/bulk
- Catalogs are collections of ToolItem IDs
- Users copy catalog tools using parent_tool_id
- Catalogs have tags for searchability
"""
import pytest
from datetime import datetime, UTC


@pytest.mark.integration
# NOTE: the five ManufacturerCatalog tests that lived here were
# removed with the v1 /api/v1/catalogs router (migration 0008; the
# v2 Catalog entity has its own suite in contract/test_catalogs_api.py).
# The role-management and bulk deep-model tests remain until their
# own R6 slice retires those endpoints.
def test_grant_manufacturer_role(client, admin_headers):
    """Test granting manufacturer role to existing user.
    
    Assumptions:
    - Admin creates user account
    - Admin grants "manufacturer" role via PATCH /users/{id}/roles
    - Can add manufacturer_profile when granting role
    - Only admin can grant roles
    """
    # Admin creates user
    user_response = client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "email": "catalog@sandvik.com",
            "password": "secure_password"
        }
    )
    assert user_response.status_code == 201
    user_data = user_response.json()
    assert user_data.get("role") in [None, "user"]  # Default role
    user_id = user_data["id"]
    
    # Admin grants manufacturer role
    response = client.patch(
        f"/api/v1/users/{user_id}/roles",
        headers=admin_headers,
        json={
            "role": "manufacturer",
            "manufacturer_profile": {
                "company_name": "Sandvik Coromant",
                "website": "https://www.sandvik.coromant.com",
                "description": "Leading manufacturer of cutting tools"
            }
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "manufacturer"
    assert data["manufacturer_profile"]["company_name"] == "Sandvik Coromant"
    assert data["is_verified"] == False  # Not yet verified as partner


@pytest.mark.integration
def test_revoke_manufacturer_role(client, admin_headers):
    """Test revoking manufacturer role from user.
    
    Assumptions:
    - Admin can revoke manufacturer role
    - User's catalogs remain but are unpublished
    - manufacturer_profile remains for historical reference
    """
    # Setup: Create user with manufacturer role
    user = client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={"email": "temp@example.com", "password": "pass"}
    ).json()
    
    client.patch(
        f"/api/v1/users/{user['id']}/roles",
        headers=admin_headers,
        json={
            "role": "manufacturer",
            "manufacturer_profile": {"company_name": "Test Co"}
        }
    )
    
    # Revoke manufacturer role
    response = client.patch(
        f"/api/v1/users/{user['id']}/roles",
        headers=admin_headers,
        json={"role": "user"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "user"
    assert "manufacturer_profile" in data  # Preserved for history


@pytest.mark.integration
def test_non_admin_cannot_grant_roles(client, user_headers, admin_headers):
    """Test that non-admin users cannot grant roles.
    
    Assumptions:
    - Only admin can modify user roles
    - Regular users get 403 Forbidden
    """
    # Create another user (admin creates it)
    target_user = client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={"email": "target@example.com", "password": "pass"}
    ).json()
    
    # Regular user tries to grant manufacturer role
    response = client.patch(
        f"/api/v1/users/{target_user['id']}/roles",
        headers=user_headers,
        json={"role": "manufacturer"}
    )
    assert response.status_code == 403


@pytest.mark.integration
def test_user_bulk_copy_catalog_tools(client, user_headers, manufacturer_headers):
    """Test user copying multiple catalog tools to their library (bulk-first).
    
    Assumptions:
    - Manufacturer has published catalog with tools
    - User copies tools (creates new ToolItems with parent_tool_id set)
    - Uses existing /api/v1/tool-items/bulk with parent_tool_id array
    - User owns the copied tools and can modify them
    """
    # Manufacturer: Create catalog tools
    mfr_tools = client.post(
        "/api/v1/tool-items/bulk",
        headers=manufacturer_headers,
        json={
            "tools": [
                {"type": "tap", "product_code": "TAP-M6", "geometry": {"thread_size": "M6x1.0"}},
                {"type": "tap", "product_code": "TAP-M8", "geometry": {"thread_size": "M8x1.25"}},
                {"type": "tap", "product_code": "TAP-M10", "geometry": {"thread_size": "M10x1.5"}}
            ]
        }
    ).json()
    
    catalog = client.post(
        "/api/v1/catalogs",
        headers=manufacturer_headers,
        json={
            "name": "Taps & Threading",
            "tool_ids": mfr_tools["tool_ids"],
            "tags": ["tap", "threading"],
            "is_published": True
        }
    ).json()
    
    # User: Copy first 2 catalog tools to their library
    response = client.post(
        "/api/v1/tool-items/bulk",
        headers=user_headers,
        json={
            "tools": [
                {"parent_tool_id": mfr_tools["tool_ids"][0]},
                {"parent_tool_id": mfr_tools["tool_ids"][1]}
            ]
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["tools_created"] == 2
    
    # Verify copied tools have parent_tool_id set
    for i, tool_id in enumerate(data["tool_ids"]):
        tool = client.get(f"/api/v1/tool-items/{tool_id}", headers=user_headers).json()
        assert tool["parent_tool_id"] == mfr_tools["tool_ids"][i]
        assert tool["type"] == "tap"
        assert tool["user_id"] != mfr_tools["tool_ids"][i]  # Different owner


@pytest.mark.integration
def test_user_bulk_create_custom_tools(client, user_headers):
    """Test user creating multiple custom tools (bulk-first).
    
    Assumptions:
    - Bulk operation for importing user's existing tool library
    - parent_tool_id is None for all (not copied from catalog)
    - User owns all ToolItems
    """
    response = client.post(
        "/api/v1/tool-items/bulk",
        headers=user_headers,
        json={
            "tools": [
                {
                    "type": "endmill",
                    "manufacturer": "Generic",
                    "product_code": "CUSTOM-001",
                    "description": "Custom shop-made cutter",
                    "geometry": {"diameter": {"value": 6.0, "unit": "mm"}}
                },
                {
                    "type": "drill",
                    "manufacturer": "Generic",
                    "product_code": "CUSTOM-002",
                    "description": "Re-ground drill",
                    "geometry": {"diameter": {"value": 5.0, "unit": "mm"}}
                }
            ]
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["tools_created"] == 2
    
    # Verify all are custom (no parent_tool_id)
    for tool_id in data["tool_ids"]:
        tool = client.get(f"/api/v1/tool-items/{tool_id}", headers=user_headers).json()
        assert tool["parent_tool_id"] is None


@pytest.mark.integration
def test_user_bulk_override_catalog_tool_specs(client, user_headers, manufacturer_headers):
    """Test user can bulk update tools copied from catalog (measured dimensions).
    
    Assumptions:
    - User's ToolItems are independent copies
    - Bulk update for efficiency (e.g., after measuring actual tools)
    - parent_tool_id reference maintained
    - Original catalog tools unchanged
    """
    # Manufacturer: Create catalog
    mfr_tools = client.post(
        "/api/v1/tool-items/bulk",
        headers=manufacturer_headers,
        json={
            "tools": [
                {"type": "insert", "product_code": "INS-1", "geometry": {"diameter": {"value": 12.7, "unit": "mm"}}},
                {"type": "insert", "product_code": "INS-2", "geometry": {"diameter": {"value": 15.9, "unit": "mm"}}}
            ]
        }
    ).json()
    
    catalog = client.post(
        "/api/v1/catalogs",
        headers=manufacturer_headers,
        json={
            "name": "Inserts",
            "tool_ids": mfr_tools["tool_ids"],
            "tags": ["insert"],
            "is_published": True
        }
    ).json()
    
    # User: Copy catalog tools
    user_tools = client.post(
        "/api/v1/tool-items/bulk",
        headers=user_headers,
        json={
            "tools": [
                {"parent_tool_id": mfr_tools["tool_ids"][0]},
                {"parent_tool_id": mfr_tools["tool_ids"][1]}
            ]
        }
    ).json()
    
    # User: Bulk update with measured dimensions
    response = client.patch(
        "/api/v1/tool-items/bulk",
        headers=user_headers,
        json={
            "updates": [
                {"id": user_tools["tool_ids"][0], "geometry": {"diameter": {"value": 12.65, "unit": "mm"}}},
                {"id": user_tools["tool_ids"][1], "geometry": {"diameter": {"value": 15.85, "unit": "mm"}}}
            ]
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["tools_updated"] == 2
    
    # Verify user tools updated
    tool1 = client.get(f"/api/v1/tool-items/{user_tools['tool_ids'][0]}", headers=user_headers).json()
    assert tool1["geometry"]["diameter"]["value"] == 12.65
    assert tool1["parent_tool_id"] == mfr_tools["tool_ids"][0]  # Reference maintained
    
    # Verify original catalog tools unchanged
    cat_tool1 = client.get(f"/api/v1/tool-items/{mfr_tools['tool_ids'][0]}", headers=manufacturer_headers).json()
    assert cat_tool1["geometry"]["diameter"]["value"] == 12.7


@pytest.mark.integration
def test_verify_manufacturer_partnership(client, admin_headers, manufacturer_headers):
    """Test admin verifying manufacturer user as official partner.
    
    Assumptions:
    - Only admin can set is_verified on manufacturer users
    - Verified manufacturers get special badge/icon in catalog listings
    - Enables analytics access for manufacturer
    - Updates manufacturer_profile metadata
    """
    # Manufacturer: Create account (unverified by default)
    mfr_user = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "email": "partner@guhring.com",
            "password": "secure",
            "role": "manufacturer",
            "manufacturer_profile": {"company_name": "Guhring"}
        }
    ).json()
    
    # Admin: Verify manufacturer partnership
    response = client.patch(
        f"/api/v1/users/{mfr_user['id']}",
        headers=admin_headers,
        json={
            "is_verified": True,
            "manufacturer_profile": {
                "company_name": "Guhring",
                "partnership_tier": "premium",
                "analytics_enabled": True
            }
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_verified"] == True
    assert data["manufacturer_profile"]["analytics_enabled"] == True
    assert data["manufacturer_profile"]["partnership_tier"] == "premium"
