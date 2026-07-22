# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for basic API functionality.

Tests the core FastAPI application setup, OpenAPI documentation,
and basic endpoint behavior.

Assumptions:
- FastAPI application is properly initialized
- OpenAPI documentation endpoints are accessible
- Root endpoint returns service information
"""
import pytest


@pytest.mark.integration
def test_root_endpoint(client):
    """Test that API health check endpoint returns service information.
    
    Args:
        client: TestClient fixture
        
    Assumptions:
    - Health check endpoint is at "/api/health"
    - Returns JSON with service, version, and status fields
    - Root "/" is now the web UI
    """
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "service" in data
    assert data["service"] == "loobric_server"
    assert "version" in data
    assert "status" in data


@pytest.mark.integration
def test_version_endpoint(client):
    """The unauthenticated /version endpoint reports the server's build identity
    (version + git commit) so a client can verify which code a server runs."""
    from loobric_server.version import __version__
    response = client.get("/api/v1/version")
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == __version__
    assert data["commit"]                 # a sha, or 'unknown' — never empty/missing


@pytest.mark.integration
def test_openapi_json_accessible(client):
    """Test that OpenAPI JSON specification is accessible.
    
    Args:
        client: TestClient fixture
        
    Assumptions:
    - OpenAPI JSON is at /api/v1/openapi.json
    - Returns valid JSON with openapi version field
    """
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "openapi" in data
    assert "info" in data


@pytest.mark.integration
def test_swagger_ui_accessible(client):
    """Test that Swagger UI documentation is accessible.
    
    Args:
        client: TestClient fixture
        
    Assumptions:
    - Swagger UI is at /api/v1/docs
    - Returns HTML content
    """
    response = client.get("/api/v1/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


@pytest.mark.integration
def test_redoc_accessible(client):
    """Test that ReDoc documentation is accessible.
    
    Args:
        client: TestClient fixture
        
    Assumptions:
    - ReDoc is at /api/v1/redoc
    - Returns HTML content
    """
    response = client.get("/api/v1/redoc")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
