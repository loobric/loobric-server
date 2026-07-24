# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Integration tests for the session cookie's Secure flag.

Tests the hardening from MCP_PLAN.md §5: the login session cookie carries the
Secure attribute under HTTPS or when forced by LOOBRIC_COOKIE_SECURE.

Assumptions:
- LOOBRIC_COOKIE_SECURE=1 forces Secure on; =0 forces it off
- Unset means auto: Secure exactly when the request arrived over https.
  The TestClient speaks plain http, so auto mode yields no Secure flag here;
  hosted deployments (behind TLS terminators that don't forward proto) set
  the env var explicitly
- The cookie remains httponly and samesite=lax in all modes
"""
import pytest


def _login_set_cookie_header(client):
    client.post("/api/v1/auth/register",
                json={"email": "u@example.com", "password": "password123"})
    response = client.post("/api/v1/auth/login",
                           json={"email": "u@example.com",
                                 "password": "password123"})
    assert response.status_code == 200
    header = response.headers.get("set-cookie", "")
    assert "session=" in header
    return header


@pytest.mark.integration
def test_cookie_not_secure_over_plain_http_by_default(client, monkeypatch):
    """Auto mode over http: no Secure attribute (LAN/solo logins keep working)."""
    monkeypatch.delenv("LOOBRIC_COOKIE_SECURE", raising=False)
    header = _login_set_cookie_header(client)
    assert "secure" not in header.lower()
    assert "httponly" in header.lower()


@pytest.mark.integration
def test_cookie_secure_when_forced(client, monkeypatch):
    """LOOBRIC_COOKIE_SECURE=1 marks the cookie Secure even over http."""
    monkeypatch.setenv("LOOBRIC_COOKIE_SECURE", "1")
    header = _login_set_cookie_header(client)
    assert "secure" in header.lower()
    assert "httponly" in header.lower()


@pytest.mark.integration
def test_cookie_secure_force_off(client, monkeypatch):
    """LOOBRIC_COOKIE_SECURE=0 explicitly disables the Secure attribute."""
    monkeypatch.setenv("LOOBRIC_COOKIE_SECURE", "0")
    header = _login_set_cookie_header(client)
    assert "secure" not in header.lower()
