# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""
Database session management.

This module provides database session management utilities including
the get_db dependency for FastAPI and session factory.
"""

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from loobric_server.config import settings

# Create database engine
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,  # Recycle connections after 1 hour
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()

def get_db() -> Session:
    """Dependency for getting database session.
    
    Yields:
        Session: Database session
        
    Example:
        @router.get("/items/{item_id}")
        def read_item(item_id: int, db: Session = Depends(get_db)):
            return db.query(Item).filter(Item.id == item_id).first()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db() -> None:
    """Initialize database tables if they don't exist.
    
    This should be called during application startup to ensure all
    database tables are created. Uses SQLAlchemy's create_all() which
    only creates tables that don't already exist - it will not overwrite
    or modify existing tables.
    
    Assumptions:
    - Safe to call multiple times
    - Does not drop or modify existing tables
    - Does not affect existing data
    """
    from loobric_server.database.schema import Base  # Import here to avoid circular imports
    from sqlalchemy import inspect

    # Always run create_all: with checkfirst (the default) it creates ONLY
    # missing tables and never touches existing ones. The old "skip when any
    # tables exist" guard meant new tables introduced by an update were never
    # created on a populated database (bit production on the v2 cutover).
    # NOTE: create_all does not ADD COLUMNS to existing tables - column
    # changes still need a manual ALTER or a migration (see ROADMAP).
    inspector = inspect(engine)
    before = set(inspector.get_table_names())
    Base.metadata.create_all(bind=engine)
    after = set(inspect(engine).get_table_names())
    created = sorted(after - before)
    if created:
        print(f"Database schema: created missing tables: {', '.join(created)}")
    else:
        print(f"Database schema: up to date ({len(after)} tables)")

    # Schema migration spine: stamp a baseline on fresh/legacy databases and
    # apply any pending migrations (idempotent). See docs/MIGRATIONS.md. A
    # failure raises MigrationError and aborts startup rather than serving a
    # half-migrated database.
    from loobric_server.migrations import run_migrations, safety_backup

    def _safety_backup() -> None:
        path = safety_backup(engine)
        if path:
            print(f"Database schema: pre-migration backup written to {path}")

    app_tables_before = before - {"schema_migrations", "sqlite_sequence"}
    result = run_migrations(
        engine,
        fresh=(len(app_tables_before) == 0),
        backup_fn=_safety_backup,
    )
    if result.applied:
        print(f"Database schema: applied migration(s) {', '.join(result.applied)} "
              f"(head {result.head})")
    elif result.stamped:
        print(f"Database schema: recorded baseline (head {result.head})")
    else:
        print(f"Database schema: migrations up to date (head {result.head})")

    # One-time data normalization (idempotent): rows created while the
    # ToolSet facade was still named "Library" carry type='library'; the
    # facade now reads only type='set' (2026-06-11 nomenclature purge).
    if "tool_sets" in after:
        normalized = normalize_legacy_data()
        if normalized:
            print(f"Database schema: normalized {normalized} tool_sets "
                  f"rows from type='library' to type='set'")


def normalize_legacy_data(target_engine=None) -> int:
    """Rewrite tool_sets rows from the pre-purge type='library' to
    type='set'. Idempotent; returns the number of rows touched."""
    from sqlalchemy import text

    with (target_engine or engine).begin() as conn:
        result = conn.execute(
            text("UPDATE tool_sets SET type = 'set' WHERE type = 'library'")
        )
        return result.rowcount or 0
