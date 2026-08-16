# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Catalogs (docs/UBIQUITOUS_LANGUAGE.md "Catalog", grilled 2026-08-16):
the sectioned named-collection table, and the retirement of the v1
`manufacturer_catalogs` deep-model substrate it replaces (an R6 slice —
that table referenced ToolItem ids and was never reachable from the v2
facade; its rows are pre-facade data, deliberately not migrated).

Idempotent: every step guards on current state (mandatory on SQLite,
where DDL auto-commits). A fresh database built at head has the table
from create_all; every step no-ops there.
"""
from sqlalchemy import text

revision = "0008"
name = "catalogs"


def _tables(conn):
    return {row[0] for row in conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table'"))}


def upgrade(conn):
    if "catalogs" not in _tables(conn):
        conn.execute(text("""
            CREATE TABLE catalogs (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                canonical JSON NOT NULL,
                clients JSON NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                version INTEGER NOT NULL,
                user_id VARCHAR(36) NOT NULL,
                created_by VARCHAR(36) NOT NULL,
                updated_by VARCHAR(36) NOT NULL
            )"""))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_catalogs_user_id "
        "ON catalogs (user_id)"))
    if "manufacturer_catalogs" in _tables(conn):
        conn.execute(text("DROP TABLE manufacturer_catalogs"))
