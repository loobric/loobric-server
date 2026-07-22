# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Fixtures for the v2 facade contract tests.

Assumptions:
- Solo mode is activated by the LOOBRIC_SOLO=1 environment variable (G1/D1):
  the server boots with a built-in solo user and unauthenticated requests
  act as that user. No registration, login, or API-key ceremony.
- The solo_client fixture is the contract: if solo mode's activation
  mechanism changes, this fixture (and the docs) change together.
"""
import pytest


@pytest.fixture
def solo_client(db_session, monkeypatch):
    """TestClient against an app booted in solo mode (LOOBRIC_SOLO=1).

    Returns:
        TestClient: client whose unauthenticated requests act as the
        built-in solo user.
    """
    from fastapi.testclient import TestClient

    monkeypatch.setenv("LOOBRIC_SOLO", "1")

    from loobric_server.main import create_app
    from loobric_server.api.auth import get_db

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
