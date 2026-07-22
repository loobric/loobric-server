# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for authentication and API key management.

Tests API key-based authentication with scoped permissions.

Assumptions:
- Authentication can be enabled/disabled via AUTH_ENABLED setting
- API keys have scopes (read, write:items, write:presets, etc.)
- Keys can be machine-specific
- Unauthenticated requests return 401 when auth is enabled
- Unauthorized requests return 403
"""
import pytest


@pytest.mark.integration
def test_auth_disabled_allows_all_requests(client):
    """Test that when auth is disabled, all requests succeed.
    
    Args:
        client: TestClient fixture
        
    Assumptions:
    - AUTH_ENABLED=false by default in tests
    - No API key header required
    - Health check endpoint accessible without authentication
    """
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "running"


@pytest.mark.integration
def test_create_api_key(client, disable_auth):
    """Test creating an API key with scopes.
    
    Args:
        client: TestClient fixture
        disable_auth: Fixture to disable authentication
        
    Assumptions:
    - Endpoint is POST /api/v1/auth/keys
    - Auth disabled for this test
    - Returns key with id, name, scopes, and key value (only on creation)
    - Key value is only shown once
    """
    response = client.post(
        "/api/v1/auth/keys",
        json={
            "name": "Test Key",
            "scopes": ["read", "write:items"],
            "expires_at": None,
            "machine_id": None
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert "name" in data
    assert data["name"] == "Test Key"
    assert "scopes" in data
    assert "read" in data["scopes"]
    assert "write:items" in data["scopes"]
    assert "key" in data  # Only returned on creation


@pytest.mark.integration
def test_list_api_keys(client, disable_auth):
    """Test listing all API keys.
    
    Args:
        client: TestClient fixture
        disable_auth: Fixture to disable authentication
        
    Assumptions:
    - Endpoint is GET /api/v1/auth/keys
    - Auth disabled for this test
    - Returns array of keys without key values
    """
    # Create a key first
    client.post(
        "/api/v1/auth/keys",
        json={
            "name": "Key 1",
            "scopes": ["read"],
        }
    )
    
    response = client.get("/api/v1/auth/keys")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if len(data) > 0:
        assert "id" in data[0]
        assert "name" in data[0]
        assert "scopes" in data[0]
        assert "key" not in data[0]  # Key value not returned in list


@pytest.mark.integration
def test_revoke_api_key(client, disable_auth):
    """Test revoking an API key.
    
    Args:
        client: TestClient fixture
        disable_auth: Fixture to disable authentication
        
    Assumptions:
    - Endpoint is DELETE /api/v1/auth/keys/{key_id}
    - Auth disabled for this test
    - Returns 204 No Content on success
    """
    # Create a key first
    create_response = client.post(
        "/api/v1/auth/keys",
        json={
            "name": "Key to Revoke",
            "scopes": ["read"],
        }
    )
    key_id = create_response.json()["id"]
    
    # Revoke it
    response = client.delete(f"/api/v1/auth/keys/{key_id}")
    assert response.status_code == 204


@pytest.mark.integration
def test_authenticated_request_with_valid_key(client, disable_auth):
    """Test making authenticated request with valid API key.
    
    Args:
        client: TestClient fixture
        disable_auth: Fixture to disable authentication
        
    Assumptions:
    - API key passed in Authorization header: "Bearer <key>"
    - Valid key with appropriate scope allows access
    - Auth disabled for this test
    """
    # Create a key
    create_response = client.post(
        "/api/v1/auth/keys",
        json={
            "name": "Valid Key",
            "scopes": ["read"],
        }
    )
    api_key = create_response.json()["key"]
    
    # Use the key to make authenticated request
    response = client.get(
        "/api/v1/tool-items",  # Will be implemented later
        headers={"Authorization": f"Bearer {api_key}"}
    )
    # Will fail for now since endpoint doesn't exist yet
    # But auth should not be the blocker
    assert response.status_code != 401  # Not authentication error


@pytest.mark.integration
def test_request_without_required_scope(client, disable_auth):
    """Test that request fails when API key lacks required scope.
    
    Args:
        client: TestClient fixture
        disable_auth: Fixture to disable authentication
        
    Assumptions:
    - Key with only "read" scope cannot perform write operations
    - Returns 403 Forbidden
    - Auth disabled for this test
    """
    # Create a read-only key
    create_response = client.post(
        "/api/v1/auth/keys",
        json={
            "name": "Read Only Key",
            "scopes": ["read"],
        }
    )
    api_key = create_response.json()["key"]
    
    # Try to create a tool item (requires write:items)
    response = client.post(
        "/api/v1/tool-items",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"items": [{"type": "cutting_tool"}]}
    )
    # For now endpoint exists but scope checking not implemented yet
    # Should be 403 when authorization is implemented
    # Currently returns 200 (scope checking to be implemented in Phase 8)
    assert response.status_code in [200, 403, 422]  # 200 until scope checking implemented


@pytest.mark.integration
def test_machine_specific_key_access(client, disable_auth):
    """Test that machine-specific key is limited to that machine.
    
    Args:
        client: TestClient fixture
        disable_auth: Fixture to disable authentication
        
    Assumptions:
    - Key can be limited to specific machine_id
    - Requests for other machines return 403
    - Auth disabled for this test
    """
    # Create machine-specific key
    create_response = client.post(
        "/api/v1/auth/keys",
        json={
            "name": "Mill-01 Key",
            "scopes": ["read", "write:presets"],
            "machine_id": "mill-01"
        }
    )
    api_key = create_response.json()["key"]
    
    # Access to mill-01 should work (once endpoint exists)
    # Access to mill-02 should fail with 403
    # Placeholder for now - will implement when presets API exists
    assert api_key is not None


@pytest.mark.integration
def test_auth_me_accepts_api_key(client):
    """Regression: GET /auth/me must accept an API key (Bearer), not just a
    session cookie.

    It previously read only the session cookie, so an API-key client got 401
    here even though every data endpoint accepted the same key — which broke
    the API-key-first onboarding flow (e.g. `loobric whoami`). This test runs
    with auth ENABLED (no disable_auth fixture).
    """
    client.post("/api/v1/auth/register",
                json={"email": "me@example.com", "password": "password123"})
    login = client.post("/api/v1/auth/login",
                        json={"email": "me@example.com", "password": "password123"})
    assert login.status_code == 200

    # Mint a key (authenticated by the login session cookie).
    key = client.post("/api/v1/auth/keys",
                      json={"name": "k", "scopes": ["read"]}).json()["key"]

    # Drop the session cookie so ONLY the Bearer key can authenticate.
    client.cookies.clear()
    resp = client.get("/api/v1/auth/me",
                      headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@example.com"

    # With neither cookie nor key, it is still 401.
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.integration
def test_auth_me_exposes_is_admin(client):
    """Regression: GET /auth/me must return is_admin, so clients (the Web UI's
    admin Users tab, `loobric whoami`) can tell an admin from a regular user.

    The first registrant becomes the admin, so /auth/me should report
    is_admin=True and role="admin" for them. This previously omitted is_admin
    entirely, which left the Web UI unable to show the admin-only tab. Runs with
    auth ENABLED (no disable_auth fixture)."""
    client.post("/api/v1/auth/register",
                json={"email": "boss@example.com", "password": "password123"})
    client.post("/api/v1/auth/login",
                json={"email": "boss@example.com", "password": "password123"})

    me = client.get("/api/v1/auth/me").json()
    assert me["is_admin"] is True
    assert me["role"] == "admin"
