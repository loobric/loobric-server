# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Cutting data presets (docs/PRESETS.md): the contribution table the
canonical `presets` union is materialized from.

No data movement — the table starts empty everywhere (existing client-section
presets are promoted by their clients through the contribution door, never
parsed server-side).

Idempotent: every step guards on current state (mandatory on SQLite, where
DDL auto-commits). A fresh database built at head has the table from
create_all; every step no-ops there.
"""
from sqlalchemy import text

revision = "0007"
name = "preset_contributions"


def _tables(conn):
    return {row[0] for row in conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table'"))}


def upgrade(conn):
    if "preset_contributions" not in _tables(conn):
        conn.execute(text("""
            CREATE TABLE preset_contributions (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                record_kind VARCHAR(16) NOT NULL,
                record_id VARCHAR(36) NOT NULL,
                origin VARCHAR(120) NOT NULL,
                label VARCHAR(255) NOT NULL,
                op_type VARCHAR(32),
                machine_id VARCHAR(36),
                data JSON NOT NULL,
                preset_schema INTEGER NOT NULL,
                source VARCHAR(255) NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                version INTEGER NOT NULL,
                user_id VARCHAR(36) NOT NULL,
                created_by VARCHAR(36) NOT NULL,
                updated_by VARCHAR(36) NOT NULL
            )"""))
    for index_sql in (
        "CREATE INDEX IF NOT EXISTS ix_preset_contrib_record "
        "ON preset_contributions (user_id, record_kind, record_id)",
        "CREATE INDEX IF NOT EXISTS ix_preset_contributions_record_id "
        "ON preset_contributions (record_id)",
        "CREATE INDEX IF NOT EXISTS ix_preset_contributions_machine_id "
        "ON preset_contributions (machine_id)",
        "CREATE INDEX IF NOT EXISTS ix_preset_contributions_user_id "
        "ON preset_contributions (user_id)",
    ):
        conn.execute(text(index_sql))
