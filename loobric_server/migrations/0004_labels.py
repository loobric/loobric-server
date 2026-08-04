# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Labels: physical QR/short-code stickers pointing at records
(docs/LABELS.md).

One new table, no data movement. A fresh database built at head already has
it from create_all; a populated pre-0004 database gets the DDL here.

Idempotent: every step guards on current state (mandatory on SQLite, where
DDL auto-commits).
"""
from sqlalchemy import text

revision = "0004"
name = "labels"


def _tables(conn):
    return {row[0] for row in conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table'"))}


def upgrade(conn):
    if "labels" not in _tables(conn):
        conn.execute(text("""
            CREATE TABLE labels (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                code VARCHAR(12) NOT NULL,
                entity_type VARCHAR(32) NOT NULL,
                entity_id VARCHAR(36),
                labeled_at DATETIME,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                version INTEGER NOT NULL,
                user_id VARCHAR(36) NOT NULL,
                created_by VARCHAR(36) NOT NULL,
                updated_by VARCHAR(36) NOT NULL
            )"""))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_labels_code ON labels (code)"))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_labels_entity_id ON labels (entity_id)"))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_labels_user_id ON labels (user_id)"))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_labels_entity "
        "ON labels (entity_type, entity_id)"))
