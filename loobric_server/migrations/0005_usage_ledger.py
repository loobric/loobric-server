# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""The usage ledger (docs/TOOL_SCHEMA.md §7.8): the append-only contribution
table, plus the entry's usage-baseline binding column.

No data movement — the ledger starts empty everywhere (pre-existing hours
are deliberately not invented; the first observation is a baseline).

Idempotent: every step guards on current state (mandatory on SQLite, where
DDL auto-commits). A fresh database built at head has the table and column
from create_all; every step no-ops there.
"""
from sqlalchemy import text

revision = "0005"
name = "usage_ledger"


def _columns(conn, table):
    return {row[1] for row in conn.execute(text("PRAGMA table_info(%s)" % table))}


def _tables(conn):
    return {row[0] for row in conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table'"))}


def upgrade(conn):
    if "usage_ledger" not in _tables(conn):
        conn.execute(text("""
            CREATE TABLE usage_ledger (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                entry_id VARCHAR(36) NOT NULL,
                machine_id VARCHAR(36) NOT NULL,
                instance_id VARCHAR(36),
                metric VARCHAR(16) NOT NULL,
                amount FLOAT NOT NULL,
                counter_value FLOAT,
                source VARCHAR(255) NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                version INTEGER NOT NULL,
                user_id VARCHAR(36) NOT NULL,
                created_by VARCHAR(36) NOT NULL,
                updated_by VARCHAR(36) NOT NULL
            )"""))
    for index_sql in (
        "CREATE INDEX IF NOT EXISTS ix_usage_ledger_entry_id "
        "ON usage_ledger (entry_id)",
        "CREATE INDEX IF NOT EXISTS ix_usage_ledger_machine_id "
        "ON usage_ledger (machine_id)",
        "CREATE INDEX IF NOT EXISTS ix_usage_ledger_instance_id "
        "ON usage_ledger (instance_id)",
        "CREATE INDEX IF NOT EXISTS ix_usage_ledger_user_id "
        "ON usage_ledger (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_usage_ledger_instance_metric "
        "ON usage_ledger (user_id, instance_id, metric)",
    ):
        conn.execute(text(index_sql))

    if "usage_baseline_instance_id" not in _columns(
            conn, "tool_table_entry_records"):
        conn.execute(text(
            "ALTER TABLE tool_table_entry_records "
            "ADD COLUMN usage_baseline_instance_id VARCHAR(36)"))
