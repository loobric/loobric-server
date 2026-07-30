# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""Setups: the transitory machine↔set relationship (MAPPING_PLAN.md, 0.7.0
BREAKING).

The set↔machine link moves off the CAM-owned set (`tool_set_records.machine_id`
+ the canonical `machine_id` field) onto its own association table,
`machine_set_maps`, with one-active-per-machine enforced by a partial unique
index. Existing links migrate to map rows: per machine, the most recently
UPDATED linked set becomes the `active` setup; every other linked set gets an
`ended` row (history preserved, nothing deleted) — pre-0.7.0 allowed many
links per machine, the new model allows one active.

Idempotent: each step guards on current state (mandatory on SQLite, where DDL
auto-commits). A fresh database built at head by create_all already has the
table and lacks the column, so every step no-ops there.
"""
import json
from datetime import datetime, UTC
from uuid import uuid4

from sqlalchemy import text

revision = "0003"
name = "machine_set_maps"


def _columns(conn, table):
    return {row[1] for row in conn.execute(text("PRAGMA table_info(%s)" % table))}


def _tables(conn):
    return {row[0] for row in conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table'"))}


def upgrade(conn):
    # 1. The table (create_all builds it on fresh DBs; legacy DBs need DDL).
    if "machine_set_maps" not in _tables(conn):
        conn.execute(text("""
            CREATE TABLE machine_set_maps (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                machine_id VARCHAR(36) NOT NULL,
                tool_set_id VARCHAR(36) NOT NULL REFERENCES tool_set_records (id),
                status VARCHAR(10) NOT NULL,
                activated_at DATETIME NOT NULL,
                ended_at DATETIME,
                activated_key VARCHAR(36),
                ended_by VARCHAR(36),
                ended_key VARCHAR(36),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                version INTEGER NOT NULL,
                user_id VARCHAR(36) NOT NULL,
                created_by VARCHAR(36) NOT NULL,
                updated_by VARCHAR(36) NOT NULL
            )"""))
        conn.execute(text(
            "CREATE INDEX ix_machine_set_maps_machine_id "
            "ON machine_set_maps (machine_id)"))
        conn.execute(text(
            "CREATE INDEX ix_machine_set_maps_tool_set_id "
            "ON machine_set_maps (tool_set_id)"))
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_active_map_per_machine "
        "ON machine_set_maps (machine_id) WHERE status = 'active'"))

    # 2. Copy existing links to map rows + strip machine_id out of stored
    #    canonical. Only meaningful on a legacy DB that still has the column.
    if "machine_id" not in _columns(conn, "tool_set_records"):
        return

    rows = conn.execute(text(
        "SELECT id, machine_id, canonical, user_id, updated_at "
        "FROM tool_set_records")).fetchall()

    # Newest updated_at per machine wins `active`; the rest become history.
    linked = [r for r in rows if r[1]]
    winners = {}
    for r in sorted(linked, key=lambda r: str(r[4] or ""), reverse=True):
        winners.setdefault((r[3], r[1]), r[0])       # (user_id, machine_id) -> set id

    now = datetime.now(UTC).isoformat(sep=" ")
    for set_id, machine_id, _canon, user_id, _upd in linked:
        already = conn.execute(text(
            "SELECT 1 FROM machine_set_maps WHERE machine_id = :m "
            "AND tool_set_id = :s"), {"m": machine_id, "s": set_id}).fetchone()
        if already:
            continue
        active = winners.get((user_id, machine_id)) == set_id
        conn.execute(text("""
            INSERT INTO machine_set_maps
                (id, machine_id, tool_set_id, status, activated_at, ended_at,
                 activated_key, ended_by, ended_key, created_at, updated_at,
                 version, user_id, created_by, updated_by)
            VALUES (:id, :m, :s, :status, :now, :ended, NULL, :ended_by, NULL,
                    :now, :now, 1, :u, :u, :u)"""),
            {"id": str(uuid4()), "m": machine_id, "s": set_id,
             "status": "active" if active else "ended",
             "now": now, "ended": None if active else now,
             "ended_by": None if active else user_id, "u": user_id})

    for set_id, _machine_id, canon, _user_id, _upd in rows:
        doc = json.loads(canon) if isinstance(canon, str) else (canon or {})
        if "machine_id" not in doc:
            continue
        doc.pop("machine_id")
        conn.execute(text(
            "UPDATE tool_set_records SET canonical = :c WHERE id = :id"),
            {"c": json.dumps(doc), "id": set_id})

    # 3. Drop the column (SQLite >= 3.35 supports DROP COLUMN directly).
    conn.execute(text("DROP INDEX IF EXISTS ix_tool_set_records_machine_id"))
    conn.execute(text("ALTER TABLE tool_set_records DROP COLUMN machine_id"))
