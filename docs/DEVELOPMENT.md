# Loobric Server Development Guide

## Development Documentation
1. **[Development Guide](DEVELOPMENT.md)** - This document 
2. **[Design Philosophy](DESIGN_PHILOSOPHY.md)** - Core principles and architecture
3. **[Authentication](AUTHENTICATION.md)** - Authentication and authorization
4. **[Architecture](ARCHITECTURE.md)** - System architecture and components
5. **[Tool Schema](TOOL_SCHEMA.md)** - The authoritative sectioned-record contract

## Development Setup

### Prerequisites
- Python 3.11+
- SQLite (development) / PostgreSQL (production)
- UV (recommended) or pip

## Quick Start for running locally

1. Fork and clone the repository:
   ```bash
   git clone https://github.com/your-username/loobric-server.git
   cd loobric-server
   ```

2. Set up the development environment:
   ```bash
   uv venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   uv pip install -e ".[dev]"
   ```

3. Run tests:
   ```bash
   pytest
   ```

4. Start the development server:
   ```bash
   uvicorn loobric_server.main:app --reload
   ```

## Repo Organization

```
loobric-server/
├── loobric_server/               # Main package
│   ├── api/             # API endpoints and routers (v2 sectioned records)
│   ├── auth/            # Authentication & authorization
│   ├── contract/        # Authoritative contract models (tool schema, §10)
│   ├── database/        # Database models and sessions
│   ├── migrations/      # Forward-only schema migrations
│   └── web/             # Web UI (single static file + assets)
├── tests/               # Test suite
│   ├── contract/        # Schema contract tests (golden fixtures)
│   ├── fixtures/        # Test fixtures
│   ├── integration/     # Integration tests
│   └── unit/            # Unit tests
├── scripts/             # One-off maintenance/migration scripts
└── docs/                # Documentation
```

## Testing

### Running Tests
```bash
# Run tests with coverage
pytest --cov=loobric_server tests/

# Run specific test file
pytest tests/unit/test_module.py

# Run with detailed output
pytest -v
```

### Authentication in Tests

**Important:** Authentication is **enabled by default** (`AUTH_ENABLED=true`). This ensures tests run in a production-like environment and catch authentication/authorization bugs.

#### Disabling Authentication for Specific Tests

Only disable authentication when absolutely necessary (e.g., testing unauthenticated endpoints). Use a pytest fixture:

```python
@pytest.fixture
def disable_auth(monkeypatch):
    """Disable authentication for tests that need it."""
    monkeypatch.setenv("AUTH_ENABLED", "false")

def test_unauthenticated_endpoint(client, disable_auth):
    """Test that works without authentication."""
    response = client.get("/api/health")
    assert response.status_code == 200
```

#### Best Practices

- **Default to auth enabled**: Write tests that properly authenticate users
- **Explicit opt-out**: Only disable auth when testing specific unauthenticated flows
- **Use fixtures**: Create reusable fixtures for common auth scenarios (admin user, normal user, etc.)
- **Test auth failures**: Verify that endpoints properly reject unauthenticated/unauthorized requests

## Database Schema & Migrations

Tables are created on startup by `init_db()` (`loobric_server/database/session.py`), which
calls SQLAlchemy `create_all` (missing tables only) and then runs the **migration
spine** (`loobric_server/migrations/`) to evolve existing tables. There is no Alembic — the
spine is a small in-repo, forward-only runner; see [MIGRATIONS.md](MIGRATIONS.md).

To change the schema of an existing table, add a migration file
`loobric_server/migrations/NNNN_name.py` exposing `revision`, `name`, and an **idempotent**
`upgrade(conn)` (guard every change — on SQLite a failed DDL is not rolled back, so a
failed migration is retried and must tolerate partial state). It runs automatically on
the next startup, and the applied set is recorded in the `schema_migrations` table.


## Testing API Endpoints

1. Start the development server:
   ```bash
   uvicorn loobric_server.main:app --reload
   ```

2. Access interactive documentation:
   - Swagger UI: http://localhost:8000/api/v1/docs
   - ReDoc: http://localhost:8000/api/v1/redoc


## Configuration

Environment variables (see `.env.example`):
- `DATABASE_URL` - Database connection string
- `AUTH_ENABLED` - Enable/disable authentication (default: true)
- `SECRET_KEY` - Session encryption key
- `LOG_LEVEL` - Logging level (DEBUG, INFO, WARNING, ERROR)

## Dependencies

Core dependencies:
- FastAPI - Web framework
- SQLAlchemy - ORM
- structlog - Structured logging
- bcrypt - Password hashing
- pytest - Testing framework
- hypothesis - Property-based testing

## Planned Future Work

Planned and aspirational work (auth hardening, notifications, log query API, and
more) is tracked in [ROADMAP.md](../ROADMAP.md), the single source of truth.