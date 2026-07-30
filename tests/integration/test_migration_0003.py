# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only

"""Migration 0003 (machine_set_maps): the set↔machine link moves off the set
onto setup rows. Pre-0.7.0 allowed many linked sets per machine; the migration
makes the most recently UPDATED one the `active` setup and preserves every
other link as an `ended` row — history, never deletion. Stored canonical loses
its `machine_id` key; the column is dropped. Idempotent on re-run."""
import json

import importlib

from sqlalchemy import create_engine, text


def _load_0003():
    return importlib.import_module("loobric_server.migrations.0003_machine_set_maps")


def _legacy_engine(tmp_path):
    """A pre-0.7.0 tool_set_records table: machine_id column, canonical with
    the machine_id field, two sets linked to the same machine + one unlinked."""
    engine = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE tool_set_records (
                id VARCHAR(36) PRIMARY KEY,
                machine_id VARCHAR(36),
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
            "CREATE INDEX ix_tool_set_records_machine_id "
            "ON tool_set_records (machine_id)"))

        def _row(sid, machine, updated):
            canonical = {
                "name": {"value": sid, "source": "asserted:freecad"},
                "machine_id": ({"value": machine, "source": "asserted:human"}
                               if machine else {"value": None, "source": "unknown"}),
                "members": [],
            }
            conn.execute(text("""
                INSERT INTO tool_set_records
                    (id, machine_id, canonical, clients, created_at, updated_at,
                     version, user_id, created_by, updated_by)
                VALUES (:id, :m, :c, '{}', :u, :u, 1, 'u1', 'u1', 'u1')"""),
                {"id": sid, "m": machine, "c": json.dumps(canonical), "u": updated})

        _row("set-old", "mach-1", "2026-06-01 10:00:00")
        _row("set-new", "mach-1", "2026-07-01 10:00:00")   # most recently updated
        _row("set-free", None, "2026-07-02 10:00:00")      # never linked
    return engine


def test_0003_moves_links_to_setup_rows(tmp_path):
    mig = _load_0003()
    engine = _legacy_engine(tmp_path)
    with engine.begin() as conn:
        mig.upgrade(conn)

    with engine.connect() as conn:
        maps = conn.execute(text(
            "SELECT tool_set_id, status FROM machine_set_maps "
            "WHERE machine_id = 'mach-1'")).fetchall()
        by_set = {r[0]: r[1] for r in maps}
        assert by_set == {"set-new": "active", "set-old": "ended"}

        # The unlinked set got no row.
        assert conn.execute(text(
            "SELECT COUNT(*) FROM machine_set_maps "
            "WHERE tool_set_id = 'set-free'")).scalar() == 0

        # Stored canonical lost machine_id; the column is gone.
        for (canon,) in conn.execute(text(
                "SELECT canonical FROM tool_set_records")):
            assert "machine_id" not in json.loads(canon)
        cols = {r[1] for r in conn.execute(text(
            "PRAGMA table_info(tool_set_records)"))}
        assert "machine_id" not in cols

        # One active per machine is enforced going forward.
        idx = [r[1] for r in conn.execute(text(
            "PRAGMA index_list(machine_set_maps)"))]
        assert "uq_active_map_per_machine" in idx


def test_0003_is_idempotent(tmp_path):
    mig = _load_0003()
    engine = _legacy_engine(tmp_path)
    with engine.begin() as conn:
        mig.upgrade(conn)
    with engine.begin() as conn:
        mig.upgrade(conn)          # second run: no duplicate rows, no errors

    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT COUNT(*) FROM machine_set_maps")).scalar() == 2
